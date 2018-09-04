# hackernews-rss-inlined-content

Loads the hackerness rss and inlines the contents of the pages. Chrome with Selenium loads the page, dom-distiller makes the contents like they're in firefox's reader mode, and the resulting html is served as the entry description. The 300 or so entries become about 5mb. PDFs and things that yield no usible text preview will remain as they were on the old feed.

I invoke it as: 

``` 
  xvfb-run python main.py
```

I used `xvfb-run` instead of headless mode because extensions are not supported in headless. One directory up, in "../dat", is a chrome user profile data directory that is copied for each instance of the browser run and deleted when finished. You can initialize it and add whatever extensions you want. The resulting rss file is then commited/pushed on here and served via gitpages. 

This is hack level code. 

The feed is available at https://damng.github.io/hackernews-rss-with-inlined-content/output.rss

If you find this useful, don't give me anything. ~~Instead, go to http://templeos.org, donate to the TempleOS project and become a Templar.~~ Dontate to the Brain and Behavior Research Foundation (https://www.bbrfoundation.org/).
