
Web interface design philosophy
-------------------------------

The web interface should be as minimal as possible.

The web interface should work with text-only browsers, modern browsers, and
everything in-between. Some may be nicer to use, but all functionality should
be available everywhere.

Fast and ugly is better than slow and pretty.


User interactions
~~~~~~~~~~~~~~~~~

.. note::

    This list might lag behing reality; anyway, it all started from here.

User interactions, by logical groups:

* entry

  * mark an entry as read
  * mark an entry as unread
  * go to an entry's link
  * go to an entry's feed
  * go to an entry's feed link

* entry list

  * see the latest unread entries
  * see the latest read entries
  * see the latest entries

* entry list (feed)

  * mark all the entries as read
  * mark all the entries as unread

* feed

  * add a feed
  * delete a feed
  * change a feed's title
  * go to a feed's entries
  * go to a feed's link

* feed list

  * see a list of all the feeds

* other

  * be notified of the success/failure of a previous action

Controls (below), mapped to user interactions:

* link

  * go to ...
  * see ...

* simple button

  * mark an entry as read
  * mark an entry as unread

* button with input

  * add a feed
  * change a feed's title

* button with checkbox

  * mark all the entries are read
  * mark all the entries are unread
  * delete a feed


Controls
~~~~~~~~

There are three interaction modes, HTML-only, HTML+CSS, and HTML+CSS+JS.
Each mode adds enhancements on top of the previous one.

In the HTML-only mode, all elements of a control are visible. Clicking the
element that triggers the action (e.g. a button) submits a form and, if
possible, redirects back to the source page, with any error messages shown
after the action element.

In the HTML+CSS mode, some elements might be hidden so that only the action
element is visible; in its inert state it should look like text. On hover,
the other elements of the control should become visible.

In the HTML+CSS+JS mode, clicking the action element results in an asynchronous
call, with the status of the action displayed after it.

Links are just links.

Simple buttons consist of a single button.

Buttons with input consist of an text input element followed by a button.
The text input are hidden when not hovered.

Buttons with checkbox consist of a checkbox, a label for the checkbox, and
a button. The checkbox and label are hidden when not hovered.


Page structure
~~~~~~~~~~~~~~

Text TBD.

.. figure:: images/redesign-01.png
  :width: 240px
  :alt: page structure, controls

  page structure, controls


Pages
~~~~~

Text TBD.



