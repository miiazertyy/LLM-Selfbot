def _split_long_line(line, max_length):
    """Break a single line that exceeds max_length into <=max_length pieces,
    preferring word boundaries. Falls back to a hard character split for
    single tokens longer than max_length (e.g. URLs)."""
    pieces = []
    current = ""
    for word in line.split(" "):
        # A single word longer than max_length, hard-split it on characters.
        while len(word) > max_length:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:max_length])
            word = word[max_length:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= max_length:
            current += " " + word
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


def split_response(response, max_length=1900):
    """Turn one reply from the model into the messages to actually send.

    A line break is a message boundary. The persona is told to break anything
    longer than an idea into "2-3 short separate messages, one after another
    like a real person would", and the model does exactly that, separating them
    with a newline:

        haha guess i'm just naturally fun 😂 you in school?

        i'm broke as hell

    This used to glue those back together with the newline intact and send one
    message with a gap in the middle, which is not a thing people do, and threw
    away the whole point of the instruction. Splitting here means each piece
    gets its own typing indicator and its own pause, so the reply arrives the
    way it was written.

    Lines longer than max_length are still broken up, because Discord rejects
    anything over 2000 characters outright.
    """
    chunks = []
    for line in (response or "").splitlines():
        line = line.strip()
        if not line:
            continue        # a blank line is the separator, not a message
        if len(line) > max_length:
            chunks.extend(_split_long_line(line, max_length))
        else:
            chunks.append(line)
    return [c for c in chunks if c]
