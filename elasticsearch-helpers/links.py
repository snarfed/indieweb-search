from elasticsearch import Elasticsearch
from bs4 import BeautifulSoup
import csv
import json

es = Elasticsearch(['http://localhost:9200'])

# Function from https://simplernerd.com/elasticsearch-scroll-python/
# All credit to them for the function
def scroll(es, index, body, scroll, size, **kw):
    page = es.search(index=index, body=body, scroll=scroll, size=size, **kw)
    scroll_id = page['_scroll_id']
    hits = page['hits']['hits']
    while len(hits):
        yield hits
        page = es.scroll(scroll_id=scroll_id, scroll=scroll)
        scroll_id = page['_scroll_id']
        hits = page['hits']['hits']

body = {"query": {"match_all": {}}} 

count = 0

domain_links = {}

link_microformat_instances = {}

# First for loop to get all links from https://simplernerd.com/elasticsearch-scroll-python/
# Get all links on each page in the index
# Write all links to a file
for hits in scroll(es, 'pages', body, '2m', 20):
    for h in hits:
        # don't count links on pages that specified nofollow in the X-Robots-Tag header
        if h["_source"].get("page_is_nofollow") and h["_source"].get("page_is_nofollow") == "true":
            continue

        soup = BeautifulSoup(h['_source']['page_content'], 'html.parser')

        links = soup.find_all('a')

        print(str(count) + " " + h["_source"]["url"])
        
        count += 1

        if not h["_source"]["incoming_links"]:
            es.update(index='pages', id=h['_id'], body={'doc': {'incoming_links': 0}})
            print('updated url')

        domain = h["_source"]["url"].split('/')[2]

        # check for nofollow or none meta values
        check_if_no_index = soup.find("meta", {"name":"robots"})

        if check_if_no_index and check_if_no_index.get("content") and ("noindex" in check_if_no_index.get("content") or "none" in check_if_no_index.get("content")):
            print("all links on {} marked as nofollow, skipping".format(h["_source"]["url"]))
            continue

        with open('links.csv', 'a') as f:
            for l in links:
                if l.has_attr('href'):
                    # skip nofollow links
                    if l.has_attr("rel") and l['rel'] == "nofollow":
                        continue
                    link = l['href'].split("?")[0].replace("#", "")
                    if l["href"].startswith("/"):
                        link = "https://" + h["_source"]["domain"] + l.get('href')
                    elif l["href"].startswith("//"):
                        link = "https:" + l.get('href')
                    elif l["href"].startswith("http"):
                        link = l.get('href')
                    else:
                        link = "https://" + h["_source"]["domain"] + "/" + l.get('href')

                    mf2_attribute = ""

                    if "u-in-reply-to" in link.class_:
                        mf2_attribute = "u-in-reply-to"
                    elif "u-like-of" in link.class_:
                        mf2_attribute = "u-like-of"
                    elif "u-repost-of" in link.class_:
                        mf2_attribute = "u-repost-of"
                    elif "u-bookmark-of" in link.class_:
                        mf2_attribute = "u-bookmark-of"
                    elif "u-url" in link.class_:
                        mf2_attribute = "u-url"
                    else:
                        mf2_attribute = ""

                    if link_microformat_instances.get(mf2_attribute):
                        link_microformat_instances[mf2_attribute] += 1
                    else:
                        link_microformat_instances[mf2_attribute] = 1
                        
                    link = link.lower()

                    try:
                        link_domain = link.split('/')[2]

                        if domain_links.get(link_domain):
                            domain_links[link_domain] += 1
                        else:
                            domain_links[link_domain] = 1

                        # don't count links to someone's own site
                        if h["_source"]["domain"] == link_domain:
                            continue
                    except:
                        continue
                    
                    csv.writer(f).writerow([h["_source"]["url"], link, link_domain])

# write domain_links to file
# may be a useful metric for determining overall domain authority
with open('domain_links.json', 'w') as f:
    json.dump(domain_links, f)

links = {}
count = 0

# Open links file
# Create dictionary with the number of times each domain appears
for line in open("links.csv"):
    line = line.strip().lower()

    link = line.split(",")

    # get domain of link
    try:
        domain_1 = link[0].split("//")[1].split("/")[0]
        domain_2 = link[1].split("//")[1].split("/")[0]
        if domain_1 != domain_2:
            if links.get(link[1]):
                links[link[1]] = links[link[1]] + 1
            else:
                links[link[1]] = 1
        count += 1
        print(count)
    except:
        print("error with link")

# write links to all_links_final.json
with open('all_links_final.json', 'w+') as f:
    json.dump(links, f)

with open('all_links_final.json', 'r') as f:
    links = json.load(f)

count = 0 

# update incoming_links attribute
for link, link_count in links.items():
    search_param = {
        "query": {
            "term": {
                "url.keyword": {
                    "value": link
                }
            }
        }
    }

    response = es.search(index="pages", body=search_param)

    if len(response["hits"]["hits"]) == 0:
        print("No results for " + link)
    else:
        try:
            link_domain = link.split('/')[2].lower()

            referring_domains = domain_links.get(link_domain)
        except:
            referring_domains = 0

        es.update(index="pages", id=response['hits']['hits'][0]['_id'], body={"doc": {"incoming_links": link_count, "referring_domains_to_site": referring_domains}})

        full_link = response['hits']['hits'][0]['_source']['url']

        print(full_link)

        count += 1
        print(count)

print("calculating top linked assets")

# sort URLs by number of incoming links
links = {k: v for k, v in sorted(links.items(), key=lambda item: item[1])}

link_origin = [i for i in links.keys()]
link_value = [i for i in links.values()]

top_ten = [[origin, value] for origin, value in zip(link_origin, link_value)[:10]]

with open('top_ten_links.csv', 'w') as f:
    csv.writer(f).writerows(top_ten)

print("calculated top 10 linked assets")
print("done")

with open('link_microformat_instances.json', 'w') as f:
    json.dump(link_microformat_instances, f)