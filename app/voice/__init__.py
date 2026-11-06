"""Live voice calls: the call brain every platform shares.

A platform adapter does two things - hands in the other person's audio as PCM, and plays out what the session
gives it. Everything that makes a call feel like a person picked up (when it answers, how it greets, turn-taking,
being interrupted, wrapping up, remembering the call afterwards) lives in session.py, once.

  audio.py     frames, sample rates, and the queue a call plays from
  vad.py       whether someone is talking, a frame at a time
  persona.py   the persona's instructions, for talking out loud
  speak.py     a voice saying one line (Groq Orpheus, the speaking chain, ElevenLabs)
  engines/     how it hears and answers: a realtime voice model, or its own brain spoken
  session.py   one call, from picking up to hanging up
  voices.py    the voices there are to pick from, and hearing one
  fake.py      a call with no platform behind it, for the tests and for Try a call
  discord.py   Discord voice channels as a call platform: hearing the channel, being heard
"""
