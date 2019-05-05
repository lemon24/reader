
Deployment
==========

For reader to actually be useful as a feed reader, feeds need to get updated
and the web application needs to be served.


Updating feeds
--------------

You can run the ``update`` command  regularly to update feeds (e.g. every
hour). Note that reader uses the ETag and Last-Modified headers, so, if
supported by the the server, feeds will only be downloaded if they changed.

To avoid waiting too much for a new feed to be updated, you can run
``update --new-only`` more often (e.g. every minute); this will update
only newly-added feeds.

You can achieve this using cron::

    42 * * * *  reader update -v 2>&1 >>"/tmp/$LOGNAME.reader.update.hourly.log"
    * * * * *   reader update -v --new-only 2>&1 >>"/tmp/$LOGNAME.reader.update.new.log"

If you are running reader on a personal computer, it might also be convenient
to run ``update`` once immediately after boot::

    @reboot     sleep 60; reader update -v 2>&1 >>"/tmp/$LOGNAME.reader.update.boot.log"


.. _deploying-app:

Serving the web application
---------------------------

reader exposes a standard WSGI application as ``reader.app.wsgi:app``.
See the `Flask documentation`_ for more details on how to deploy it.
The path to the reader database can be configured through the ``READER_DB`` 
environment variable.

.. warning::

    The web application has no authentication / authorization whatsoever;
    it is expected a server / middleware will provide that.
    

An example uWSGI configuration file (probably not idiomatic, from `here`_)::

    [uwsgi]
    socket = /apps/reader/uwsgi/sock
    manage-script-name = true
    mount = /reader=reader.app.wsgi:app
    plugin = python3
    virtualenv = /apps/reader/
    env = READER_DB=/data/www-data/reader.sqlite

You can also run the web application with the ``serve`` command.
``serve`` uses `Werkzeug's development server`_, so it probably won't scale
well past a single user.

If running on a personal computer, you can use cron to run ``serve`` at boot::

    @reboot     sleep 60; reader serve -p 8080 2>&1 ) >>"/tmp/$LOGNAME.reader.serve.boot.log"

    
.. _here: https://github.com/lemon24/owncloud/blob/936b0aa6015eb8b4a42e37ff7dc8df2bae87263d/reader.yaml#L79
.. _Flask documentation: http://flask.pocoo.org/docs/1.0/deploying/
.. _Werkzeug's development server: http://werkzeug.pocoo.org/docs/0.14/serving/#werkzeug.serving.run_simple
