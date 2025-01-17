import requests
import mf2py
import datetime
import feedparser
import microformats2
from time import mktime
from crawler.url_handling import crawl_urls
import concurrent.futures
import logging
import config
import os

# ignore insecure request warning
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

HEADERS = {
    "Authorization": config.ELASTICSEARCH_API_TOKEN,
    "Content-Type": "application/json"
}

feeds = requests.post("https://es-indieweb-search.jamesg.blog/feeds", headers=HEADERS).json()

# get url of all feeds
feed_url_list = [f[1] for f in feeds]

feeds_parsed = {}

def poll_feeds(f):
    url = f[1]
    feed_etag = f[2]
    mime_type = f[4]

    # used to skip duplicate entries in feeds.txt
    if feeds_parsed.get(url.lower()):
        return

    feeds_parsed[url.lower()] = ""

    # request will return 304 if feed has not changed based on provided etag
    r = requests.get(url, headers={'If-None-Match': feed_etag.strip()})

    # get etag
    etag = r.headers.get('etag')

    if r.status_code == 304:
        print("Feed {} unchanged".format(url))
        return
    elif r.status_code != 200:
        print("{} status code returned while retrieving {}".format(r.status_code, url))
        return

    if r.headers.get('content-type'):
        content_type = r.headers['content-type']
    else:
        content_type = ""

    print("polling " + url)

    site_url = "https://" + url.split("/")[2] 

    allowed_xml_content_types = ['application/rss+xml', 'application/atom+xml']

    if content_type in allowed_xml_content_types or mime_type in allowed_xml_content_types or mime_type == "feed":
        feed = feedparser.parse(url)

        etag = feed.get("etag", "")

        if etag == feed_etag:
            print("{} has not changed since last poll, skipping".format(url))
            return

        last_modified = feed.get("modified_parsed", None)

        if last_modified and datetime.datetime.fromtimestamp(mktime(last_modified)) < datetime.datetime.now() - datetime.timedelta(hours=12):
            print("{} has not been modified in the last 12 hours, skipping".format(url))
            return

        for entry in feed.entries:
            site_url = "https://" + entry.link.split("/")[2]
            crawl_urls({entry.link: ""}, [], 0, [], [], {}, [], site_url, 1, entry.link, False, feeds, feed_url_list, False)

            print("crawled {} url".format(entry.link))

        # update etag
        f[2] = etag

        modify_feed = requests.post("https://es-indieweb-search.jamesg.blog/update_feed", headers=HEADERS, json={"item": f})

        if modify_feed.status_code != 200:
            print("{} status code returned while modifying {}".format(modify_feed.status_code, url))
        else:
            print("updated etag for {}".format(url))
    elif mime_type == "h-feed":
        mf2_raw = mf2py.parse(r.text)

        for item in mf2_raw["items"]:
            if item.get("type") and item.get("type")[0] == "h-feed" and item.get("children"):
                for child in item["children"]:
                    jf2 = microformats2.to_jf2(child)
                    if jf2.get("url"):
                        if type(jf2["url"]) == list:
                            jf2["url"] = jf2["url"][0]
                        if jf2["url"].startswith("/"):
                            jf2["url"] = site_url + jf2["url"]

                        crawl_urls({jf2["url"]: ""}, [], 0, [], [], {}, [], site_url, 1, jf2["url"], False, feeds, feed_url_list, False)

                        print("crawled {} url".format(jf2["url"]))

    elif mime_type == "application/json":
        # parse as JSON Feed per jsonfeed.org spec

        items = r.json().get("items")

        if items and len(items) > 0:
            for item in items:
                if item.get("url"):
                    crawl_urls({item["url"]: ""}, [], 0, [], [], {}, [], "https://" + site_url, 1, item["url"], False, feeds, feed_url_list, False)

                    print("crawled {} url".format(item["url"]))

    elif mime_type == "websub":
        # send request to renew websub if the websub subscription has expired

        expire_date = f.get("expire_date")

        if f.get("websub_sent") != True or datetime.datetime.now() > datetime.datetime.strptime(expire_date, "%Y-%m-%dT%H:%M:%S.%fZ"):
            # random string of 20 letters and numbers
            # each websub endpoint needs to be different

            headers = {
                "Authorization": config.ELASTICSEARCH_API_TOKEN
            }

            r = requests.post("https://es-indieweb-search.jamesg.blog/create_websub", headers=headers, data={"website_url": url})

            r = requests.post(url, headers={'Content-Type': 'application/x-www-form-urlencoded'}, data="hub.mode=subscribe&sub.topic={}&hub.callback=https://es-indieweb-search.jamesg.blog/websub/{}".format(url, r.get_json()["key"]))

            print("sent websub request to {}".format(url))

        pass

    if etag == None:
        etag = ""
        
    return url, etag, f

def process_feeds():
    feeds_indexed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(poll_feeds, item) for item in feeds]
        
        while len(futures) > 0:
            for future in concurrent.futures.as_completed(futures):
                feeds_indexed += 1

                print("FEEDS INDEXED: {}".format(feeds_indexed))
                logging.info("FEEDS INDEXED: {}".format(feeds_indexed))
                
                try:
                    url, etag, full_item = future.result()

                    feeds.append([url, etag])

                    if etag:
                        full_item["etag"] = etag

                except Exception as e:
                    pass

                futures.remove(future)

def process_crawl_queue_from_websub():
    r = requests.get("https://es-indieweb-search.jamesg.blog/crawl_queue", headers=headers)

    pages_indexed = 0

    to_crawl = r.json()

    domains_indexed = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(crawl_urls, {item: ""}, [], 0, [], [], {}, [], "https://" + item, 1, item, feeds, feed_url_list, False) for item in to_crawl]
        
        while len(futures) > 0:
            for future in concurrent.futures.as_completed(futures):
                pages_indexed += 1

                print("PAGES INDEXED: {}".format(pages_indexed))
                logging.info("PAGES INDEXED: {}".format(pages_indexed))

                try:
                    domain = url_indexed.split("/")[2]

                    domains_indexed[domain] = domains_indexed.get(domain, 0) + 1

                    if domains_indexed[domain] > 50:
                        print("50 urls have been crawled on {}, skipping".format(domain))
                        continue

                    url_indexed, discovered = future.result()

                    if url_indexed == None:
                        futures = []
                        break
                    
                except Exception as e:
                    print(e)
                    pass

                futures.remove(future)

def process_sitemaps():
    r = requests.get("https://es-indieweb-search.jamesg.blog/sitemaps", headers=headers)

    pages_indexed = 0

    to_crawl = r.json()

    domains_indexed = {}

    sitemap_urls = []

    for item in to_crawl:
        sitemap_urls.append(item[0])

        domain = item[0].split("/")[2]

        domains_indexed[domain] = domains_indexed.get(domain, 0) + 1

        if domains_indexed[domain] > 50:
            print("50 urls have been crawled on {}, skipping".format(domain))
            continue

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(crawl_urls, {item: ""}, [], 0, [], [], {}, [], "https://" + item, 1, item, feeds, feed_url_list, False) for item in sitemap_urls]
        
        while len(futures) > 0:
            for future in concurrent.futures.as_completed(futures):
                pages_indexed += 1

                print("PAGES INDEXED: {}".format(pages_indexed))
                logging.info("PAGES INDEXED: {}".format(pages_indexed))

                try:
                    url_indexed, _ = future.result()

                    if url_indexed == None:
                        futures = []
                        break
                except Exception as e:
                    print(e)
                    pass

                futures.remove(future)

process_feeds()
# process_crawl_queue_from_websub()
# process_sitemaps()

# if results.json exists, remove
if os.path.exists("/home/james/crawler/results.json"):
    os.remove("/home/james/crawler/results.json")