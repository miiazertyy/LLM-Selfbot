"""How a call is heard and answered. Two ways, one interface (base.Engine):

  realtime.py   a voice model that hears and speaks itself - Gemini Live or OpenAI Realtime. The most human: it
                hears tone, can be talked over, and answers in about half a second.
  cascade.py    its own brain, out loud - the hearing models, the persona's own reply models, a voice. Free on
                Groq, and exactly the persona that texts them, but a second or two behind.
"""
