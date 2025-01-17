from flask import request, abort, jsonify, Blueprint
from elasticsearch import Elasticsearch
import mysql.connector
import datetime
import string
import random
import config

es = Elasticsearch(['http://localhost:9200'])

database_methods = Blueprint('database_methods', __name__)

@database_methods.route("/count")
def show_num_of_pages():
    count = es.count(index="pages")

    # read domains.txt file
    with open("domains.txt", "r") as f:
        domains = f.readlines()

    return jsonify({"es_count": count, "domains": len(domains)})

@database_methods.route("/random")
def random_page():
    if request.args.get("pw") != config.ELASTICSEARCH_PASSWORD:
        return abort(401)
        
    # read domains.txt file
    with open("domains.txt", "r") as f:
        domains = f.readlines()

    # get random domain
    domain = domains[random.randint(0, len(domains) - 1)].strip()

    return jsonify({"domain": domain})

# return feeds associated with URL
@database_methods.route("/feeds", methods=["GET", "POST"])
def get_feeds_for_url():
    if not request.headers.get("Authorization") or request.headers.get("Authorization") != config.ELASTICSEARCH_API_TOKEN:
        abort(401)

    if request.method == "POST":
        website_url = request.form.get("website_url")

        if website_url:
            database = mysql.connector.connect(
                host="localhost",
                user=config.MYSQL_DB_USER,
                password=config.MYSQL_DB_PASSWORD,
                database="feeds"
            )

            cursor = database.cursor(buffered=True)

            cursor.execute("SELECT * FROM feeds WHERE website_url = %s", (website_url,))

            cursor.close()

            if cursor.fetchall():
                return jsonify(cursor.fetchall())
            else:
                return jsonify({"message": "No results matching this URL were found."})
        else:
            database = mysql.connector.connect(
                host="localhost",
                user=config.MYSQL_DB_USER,
                password=config.MYSQL_DB_PASSWORD,
                database="feeds"
            )
            cursor = database.cursor(buffered=True)

            cursor.execute("SELECT * FROM feeds")
            
            item_to_return = cursor.fetchall()

            cursor.close()

            return jsonify(item_to_return)

    return jsonify({"message": "Method not allowed."}), 405

@database_methods.route("/save", methods=["POST"])
def save_feed():
    if not request.headers.get("Authorization") or request.headers.get("Authorization") != config.ELASTICSEARCH_API_TOKEN:
        abort(401)

    if request.method == "POST":
        result = request.get_json()["feeds"]

        for r in result:
            database = mysql.connector.connect(
                host="localhost",
                user=config.MYSQL_DB_USER,
                password=config.MYSQL_DB_PASSWORD,
                database="feeds"
            )
            cursor = database.cursor(buffered=True)

            cursor.execute("SELECT * FROM feeds WHERE website_url = %s AND feed_url = %s AND mime_type = %s", (r["website_url"], r["feed_url"], r["mime_type"]))

            if cursor.fetchone():
                # delete feed because it already exists to make room for the new feed
                cursor.execute("DELETE FROM feeds WHERE website_url = %s AND feed_url = %s AND mime_type = %s", (r["website_url"], r["feed_url"], r["mime_type"]))

            cursor.execute("INSERT INTO feeds (website_url, feed_url, etag, discovered, mime_type) VALUES (%s, %s, %s, %s, %s)", (r["website_url"], r["feed_url"], r["etag"], r["discovered"], r["mime_type"]))

            database.commit()

            cursor.close()

        return jsonify({"message": "Feeds successfully saved."})

    return 200

@database_methods.route("/create_crawled", methods=["POST"])
def create_crawled_site():
    if not request.headers.get("Authorization") or request.headers.get("Authorization") != config.ELASTICSEARCH_API_TOKEN:
        abort(401)
        
    if request.method == "POST":
        url = request.form.get("url")
        
        if url:
            database = mysql.connector.connect(
                host="localhost",
                user=config.MYSQL_DB_USER,
                password=config.MYSQL_DB_PASSWORD,
                database="feeds"
            )

            cursor = database.cursor(buffered=True)
            
            cursor.execute("SELECT * FROM crawled WHERE domain = %s", (url,))
            
            if cursor.fetchone():
                cursor.close()
                return jsonify({"message": "This site has already been crawled."})
            else:
                now = datetime.datetime.now()
                # now to string
                now_string = now.strftime("%Y-%m-%d %H:%M:%S")

                cursor.execute("INSERT INTO crawled (domain, crawled_on) VALUES (%s, %s)", (url, now_string, ))
                
                database.commit()

                cursor.close()
                
                return jsonify({"message": "Site successfully added to the crawled table."})
        else:
            return jsonify({"message": "No URL was provided."})
        
    return jsonify({"message": "Method not allowed."}), 405

@database_methods.route("/create_sitemap", methods=["POST"])
def create_sitemap():
    if not request.headers.get("Authorization") or request.headers.get("Authorization") != config.ELASTICSEARCH_API_TOKEN:
        abort(401)

    if request.method == "POST":
        # get json data
        website_url = request.form.get("domain")
        sitemap_url = request.form.get("sitemap_url")

        if website_url:
            database = mysql.connector.connect(
                host="localhost",
                user=config.MYSQL_DB_USER,
                password=config.MYSQL_DB_PASSWORD,
                database="feeds"
            )

            cursor = database.cursor(buffered=True)

            cursor.execute("SELECT * FROM sitemaps WHERE domain = %s", (website_url,))

            if cursor.fetchone():
                cursor.close()
                return jsonify({"message": "Sitemap already exists."})
            else:
                cursor.execute("INSERT INTO sitemaps (domain, sitemap_url) VALUES (%s, %s)", (website_url, sitemap_url))

                database.commit()

                cursor.close()

                return jsonify({"message": "Sitemap successfully created."})
        else:
            return jsonify({"message": "No website URL was provided."})

    return jsonify({"message": "Method not allowed."}), 405

@database_methods.route("/create_websub", methods=["POST"])
def create_websub():
    if not request.headers.get("Authorization") or request.headers.get("Authorization") != config.ELASTICSEARCH_API_TOKEN:
        abort(401)

    if request.method == "POST":
        result = request.get_json()

        database = mysql.connector.connect(
            host="localhost",
            user=config.MYSQL_DB_USER,
            password=config.MYSQL_DB_PASSWORD,
            database="feeds"
        )

        cursor = database.cursor(buffered=True)

        cursor.execute("SELECT * FROM websub WHERE url = %s", (result["website_url"],))

        if cursor.fetchone():
            cursor.execute("DELETE FROM websub WHERE url = %s", (result["website_url"],))

        random_string = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(20))

        cursor.execute("INSERT INTO websub (url, random_string) VALUES (%s, %s)", (result["website_url"], random_string))

        database.commit()

        cursor.close()

        return jsonify({"key": random_string})

    return jsonify({"message": "Method not allowed."}), 405

@database_methods.route("/update_feed", methods=["POST"])
def update_feed():
    if not request.headers.get("Authorization") or request.headers.get("Authorization") != config.ELASTICSEARCH_API_TOKEN:
        abort(401)

    database = mysql.connector.connect(
        host="localhost",
        user=config.MYSQL_DB_USER,
        password=config.MYSQL_DB_PASSWORD,
        database="feeds"
    )

    cursor = database.cursor(buffered=True)

    item = request.get_json()

    cursor.execute("SELECT * FROM feeds WHERE feed_url = %s", (item.get("feed_url"),))

    feeds = cursor.fetchone()

    if feeds and len(feeds) > 0:
        cursor.execute("UPDATE feeds SET etag = %s, last_modified = %s WHERE feed_url = %s", (item.get("etag"), item.get("last_modified"), item.get("feed_url")))

        database.commit()

        cursor.close()

        return 200

    cursor.close()
    
    abort(400)

@database_methods.route("/websub/<string:id>", methods=["GET", "POST"])
def websub(id):
    database = mysql.connector.connect(
        host="localhost",
        user=config.MYSQL_DB_USER,
        password=config.MYSQL_DB_PASSWORD,
        database="feeds"
    )

    cursor = database.cursor(buffered=True)

    subscriptions = cursor.execute("SELECT * FROM websub WHERE random_string = %s", (id,)).fetchone()

    if request.method == "GET":
        if id in subscriptions:
            challenge = request.args.get("hub.challenge")

            return challenge, 200
        else:
            return "", 404

    if subscriptions and len(subscriptions) > 0:
        # treat "fat pings" as regular requests because we need to crawl a page as is
        # reference: https://indieweb.org/How_to_publish_and_consume_WebSub#How_to_Subscribe

        cursor.execute("INSERT INTO crawl_queue (url) VALUES (%s)", (subscriptions[0][0],))

        database.commit()

        cursor.close()

        return "", 200
    else:
        cursor.close()
        return "", 400