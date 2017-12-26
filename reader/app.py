from flask import Flask, render_template, current_app
app = Flask(__name__)

@app.route('/')
def root():
    entries = current_app.db.execute("""
        SELECT
            feeds.title as feed_title,
            feeds.link as feed_link,
            entries.title as title,
            entries.link as link,
            entries.published as published,
            entries.updated as updated,
            entries.enclosures as enclosures
        FROM entries, feeds
        WHERE feeds.url = entries.feed
        ORDER BY entries.published DESC, entries.updated DESC;
    """)
    return render_template('root.html', entries=entries)


