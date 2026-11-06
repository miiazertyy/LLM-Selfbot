"""WhatsApp: a persona texting from a phone number of its own.

The tenth platform, and the first here that needs no browser at all. It speaks WhatsApp's own protocol over a
WebSocket (the baileys package), the way the WhatsApp app on a linked device does - so there is no page to read,
no selectors to break, and nothing to scrape.

What lives here is the Python half: linking a number (link.py), which is a person typing an eight-digit code into
WhatsApp on their phone, or scanning a QR code with it. The runner itself is Node, beside the other runners in
app/platforms/snapchat/, because that is where their node_modules is.
"""
