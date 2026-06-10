def _split_long_line(line, max_length):
    """Break a single line that exceeds max_length into <=max_length pieces,
    preferring word boundaries so words aren't cut in half. Falls back to a
    hard character split for single tokens longer than max_length (e.g. URLs)."""
    pieces = []
    current = ""
    for word in line.split(" "):
        # A single word longer than max_length — hard-split it on characters.
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
    lines = response.splitlines()
    chunks = []
    current_chunk = ""
    for line in lines:
        # Guard against a single line that is itself longer than the limit —
        # without this, such a line would be emitted as an oversized chunk and
        # Discord would reject the send (2000-char hard cap).
        if len(line) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            chunks.extend(_split_long_line(line, max_length))
        elif len(current_chunk) + len(line) + 1 > max_length:
            chunks.append(current_chunk.strip())
            current_chunk = line
        else:
            current_chunk += "\n" + line if current_chunk else line
    if current_chunk:
        chunks.append(current_chunk.strip())
    # Drop any empty chunks that can arise from leading overflow / blank lines.
    return [c for c in chunks if c]
