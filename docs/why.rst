

Why *reader*?
=============


Why use a feed reader library?
------------------------------

Have you been unhappy with existing feed readers and wanted to make your own, but:

* never knew where to start?
* it seemed like too much work?
* you don't like writing backend code?

Are you already working with `feedparser`_, but:

* want an easier way to store, filter, sort and search feeds and entries?
* want to get back type-annotated objects instead of dicts?
* want to restrict or deny file-system access?
* want to change the way feeds are retrieved by using the more familiar `requests`_ library?
* want to also support `JSON Feed`_?

... while still supporting all the feed types feedparser does?

If you answered yes to any of the above, *reader* can help.


.. _feedparser: https://feedparser.readthedocs.io/en/latest/
.. _requests: https://requests.readthedocs.io
.. _JSON Feed: https://jsonfeed.org/


Why make your own feed reader?
------------------------------

So you can:

* have full control over your data
* control what features it has or doesn't have
* decide how much you pay for it
* make sure it doesn't get closed while you're still using it
* really, it's `easier than you think`_

Obviously, this may not be your cup of tea, but if it is, *reader* can help.


.. _easier than you think: https://rachelbythebay.com/w/2011/10/26/fred/



Why make a feed reader library?
-------------------------------

I wanted a feed reader that is:

* accessible from multiple devices
* fast
* with a simple UI
* self-hosted (for privacy reasons)
* modular / easy to extend (so I can change stuff I don't like)
* written in Python (see above)

The fact that I couldn't find one extensible enough bugged me so much that I decided to make my own; a few years later, I ended up with what I would've liked to use when I first started.
