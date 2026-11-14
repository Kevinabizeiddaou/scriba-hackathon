"""Office simulator for Scriba Executive Desk.

A fictional executive office, a controlled clock and a stream of incoming
work, driven through the Desk's real workflow (intake worker, plans, Scriba
approval cards, execution gate, verification) against an isolated sandbox
world. Nothing here is a second agent: the simulator plays the OUTSIDE WORLD
(people who send mail, providers that fail, time that passes) and the
EXECUTIVE (who approves, rejects or edits), and then measures what the Desk
did.

Everything is synthetic. Every address is under a reserved example domain.
"""

__version__ = "0.1.0"
