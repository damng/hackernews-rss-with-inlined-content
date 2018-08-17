import datetime
import multiprocessing
import shutil
import sqlite3
import sys
import tempfile
import typing
import time
import urllib
import logging
import subprocess

import attr
import bs4
import dateutil.parser
import feedgenerator
import feedparser
import progressbar
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# count for progress bar and lock for db
complete_counter = multiprocessing.Value("i", 0)

# Just me on my poor 7 year old phone. so sad like the folk on irc.rizon.net #apu.
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 4.2.1; en-us; Nexus 5 Build/JOP40D) AppleWebKit/535.19 (KHTML, like Gecko) Chrome/18.0.1025.166 Mobile Safari/535.19"
)

# nice gooble code that removes. artisnal dom elements.
with open("domdistiller.js", "r") as fid:
    DOM_DISTILLER_JS = fid.read()


@attr.s(frozen=True, slots=True)
class FeedTuple(object):
    title: str = attr.ib()
    entry: str = attr.ib()
    description: str = attr.ib()
    content_type: str = attr.ib()
    pubdate: datetime.datetime = attr.ib()


# Little sqlite3 db to store ones we've done.
class hnentries(object):

    def __init__(self, db_file="hn.sqlite3"):
        self._connection = sqlite3.connect(db_file)

    def __del__(self):
        self._connection.close()

    def __contains__(self, id) -> bool:
        c = self._connection.cursor()
        c.execute(f"select count(*) from cleaned where id=?;", (id,))
        return int(c.fetchall()[0][0]) > 0

    def get(self, item: int) -> str:
        c = self._connection.cursor()
        c.execute("select contents from cleaned where id=?;", (item,))
        res = c.fetchall()
        if len(res) < 1:
            raise KeyError
        c.close()
        return str(res[0][0])

    def set(self, key: int, value: str):
        c = self._connection.cursor()
        c.execute(
            f"insert or replace into cleaned (id,contents) values (?,?)", (key, value)
        )
        self._connection.commit()
        c.close()

    def all(self) -> typing.Sequence[typing.Tuple[int, str]]:
        c = self._connection.cursor()
        c.execute("select id, contents from cleaned;")
        res = c.fetchall()
        for row in res:
            yield row
        c.close()


def clean(url: str, moble_flag : bool = True) -> str:
    """
    Open page in chrome. Clean up dom.
    :param url:
    :return:
    """
    with tempfile.TemporaryDirectory() as tdir:
        chrome_options = Options()
        if moble_flag:
            chrome_options.add_experimental_option(
                "mobileEmulation",
                {
                    "deviceMetrics": {"width": 360, "height": 640, "pixelRatio": 3.0},
                    "userAgent": USER_AGENT,
                },
            )
        shutil.rmtree(tdir)
        shutil.copytree("../dat", tdir)
        chrome_options.add_argument(f"--user-data-dir={tdir}")
        chrome_options.add_argument("--incognito")
        chrome_options.add_argument("--disable-gpu")
        driver = webdriver.Chrome(chrome_options=chrome_options)
        driver.get(url)
        driver.execute_script(DOM_DISTILLER_JS)
        new_html = driver.execute_script(
            """
            ok = org.chromium.distiller.DomDistiller.apply();
            return ok[2][1];
        """
        )
        driver.close()
        return new_html



def clean_through_fb(url: str, moble_flag : bool = True) -> str:
    """
    Pretend we clicked the link on facebook. Click through. Clean up dom.
    :param url:
    :return:
    """
    with tempfile.TemporaryDirectory() as tdir:
        chrome_options = Options()
        if moble_flag:
            chrome_options.add_experimental_option(
                "mobileEmulation",
                {
                    "deviceMetrics": {"width": 360, "height": 640, "pixelRatio": 3.0},
                    "userAgent": USER_AGENT,
                },
            )
        shutil.rmtree(tdir)
        shutil.copytree("../dat", tdir)
        chrome_options.add_argument(f"--user-data-dir={tdir}")
        chrome_options.add_argument("--incognito")
        chrome_options.add_argument("--disable-gpu")
        driver = webdriver.Chrome(chrome_options=chrome_options)
        driver.get(f"https://l.facebook.com/l.php?u={url}")
        l = driver.find_element_by_link_text("Follow link")
        l.click()
        driver.execute_script(DOM_DISTILLER_JS)
        new_html = driver.execute_script(
            """
            return org.chromium.distiller.DomDistiller.apply()[2][1];
        """
        )
        driver.close()
        return new_html


def invert_feed(feed: str) -> str:
    """
    Go through each element of the feed.
    :param feed:
    :return:
    """
    parsed = feedparser.parse(feed)
    out_feed = feedgenerator.Rss201rev2Feed("Hackernews - Inlined Content Feed", "", "")
    pool = multiprocessing.Pool(8)
    rs = pool.map_async(process_entry, parsed["entries"])
    pool.close()
    max_value = len(parsed["entries"])
    with progressbar.ProgressBar(max_value=max_value) as bar:
        while True:
            if rs.ready():
                break
            bar.update(min(complete_counter.value,max_value))
            time.sleep(1)

    for i in rs.get():
        out_feed.add_item(
            i.title, i.entry, i.description, content=i.content_type, pubdate=i.pubdate
        )

    return out_feed.writeString(encoding="utf-8")


def process_entry(entry):
    db = hnentries()
    try:
        old_url = entry["link"]

        # Test opening the link
        r = requests.get(old_url, timeout=60, headers={"User-Agent": USER_AGENT})

        # no pdfs (yet?)
        content_type = r.headers.get("Content-Type", "text/plain")
        if "pdf" in content_type.lower():
            logging.info(f"pdf: {old_url}")
            raise Exception

        # off site.
        hn_url_raw = bs4.BeautifulSoup(entry["description"], "html.parser")("a")[0]
        raw_attrs_href_ = hn_url_raw.attrs["href"]
        hn_url = urllib.parse.urlparse(raw_attrs_href_)
        hn_id = int(urllib.parse.parse_qs(hn_url.query)["id"][0])
        with complete_counter.get_lock():
            not_in_db = hn_id not in db

        # uggo
        if not_in_db:
            if "wsj.com/" in old_url:
                cleaned_html = clean_through_fb(old_url)
            else:
                cleaned_html = clean(old_url)
            with complete_counter.get_lock():
                db.set(hn_id, cleaned_html)
        else:
            with complete_counter.get_lock():
                cleaned_html = db.get(hn_id)
        with complete_counter.get_lock():
            complete_counter.value += 1
        if cleaned_html == '':
            logging.info(f"Empty Entry {old_url}. Trying Desktop")
            cleaned_html = clean(old_url,moble_flag=False)
            if cleaned_html == '':
                logging.info(f"Empty Entry {old_url}. ")
                raise Exception

        # Successful.
        del db
        return FeedTuple(
            title=entry["title"],
            entry=raw_attrs_href_,
            description=cleaned_html,
            content_type=content_type,
            pubdate=dateutil.parser.parse(entry["published"]),
        )
    except:
        # Unable to invert feed entry. :(
        logging.exception("Unable to invert")
        del db
        with complete_counter.get_lock():
            complete_counter.value += 1
        return FeedTuple(
            title=entry["title"],
            entry=entry["link"],
            description=entry["description"],
            content_type="text/html",
            pubdate=dateutil.parser.parse(entry["published"]),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            time.sleep(30)
            logging.info("Running ... ")
            rss = requests.get("https://news.ycombinator.com/bigrss").text
            with open("docs/output.rss", "w") as newrss:
                feed = invert_feed(rss)
                newrss.write(feed)
            # commit it
            logging.info("Updating git")
            subprocess.call(
                ['git',
                 '-c',
                 'user.email=okokok@okokok.ok',
                 '-c',
                 'user.name=Davis Terrence',
                 'commit',
                 '-a',
                 '-m',
                 str(datetime.datetime.now())]
            )
            subprocess.call(
                ['git',
                 '-c',
                 'user.email=okokok@okokok.ok',
                 '-c',
                 'user.name=Davis Terrence',
                 'push']
            )
            time.sleep(1800)
        except KeyboardInterrupt:
            sys.exit(0)
        except:
            logging.exception("")
