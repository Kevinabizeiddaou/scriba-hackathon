"""What a message asks of the executive, sentence by sentence. Pure.

Three questions the rule-based path could not answer, and that decided
whether work was silently lost:

1. **Is it established that this message needs nothing?** "No action" is a
   positive finding: the message says so, or it is a bare acknowledgement.
   Anything else written by a person
   is NOT known to need nothing, and is handed over.
2. **Does it ask for more than one thing?** A message is split into
   sentences; each sentence that asks the executive to do something is a
   request of its own, with its own deadline. A request that is identified
   and not acted on keeps the run from being complete.
3. **Is this reply the answer, or a promise of one?** A reply that only says
   the answer is still coming does not satisfy a wait.

These read FORMS (an imperative with "please", "could you", "I need you to",
a statement that something is not there yet), not lists of topics, so they
do not depend on what the request is about.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional

from . import reading

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_GREETING = re.compile(r"^\s*(?:hi|hello|hey|dear|good (?:morning|afternoon|evening))\b[^,\n]{0,40},?\s*$", re.I)
_SIGN_OFF = re.compile(r"^\s*(?:thanks|thank you|many thanks|best|best regards|kind regards|regards|cheers|"
                       r"yours|sincerely|warm regards|all the best)\b[\s,!.]*(?-i:(?:[A-Z][\w.'-]*\s*){0,3})$", re.I)
_QUOTED = re.compile(r"^\s*(?:>|on .{0,80} wrote:|from:|sent:|-{2,}\s*original message)", re.I)

# The forms a request to the reader takes.
_ASK = re.compile(
    r"\bplease\b(?!\s+(?:find|see|note)\b)"
    r"|\b(?:could|can|would|will)\s+you\b|\bwould you mind\b"
    r"|\b(?:i|we)(?:\s+\w+){0,2}\s+(?:need|want|require|would like|expect)\s+(?:you|your)\b"
    r"|\b(?:needs?|requires?|awaits?|awaiting|waiting (?:for|on))\s+(?:\w+\s+){0,3}?(?:your|from you)\b"
    r"|\bit would (?:help|be (?:good|great|useful))\b.{0,20}\bif you\b"
    r"|\byou (?:need|have|will need) to\b|\bmake sure (?:you|to)\b|\bdon'?t forget to\b|\bremember to\b"
    r"|\b(?:is|are) (?:needed|required|due|expected) (?:from you|by)\b", re.I)
# Asking to be answered about THIS message is not a second piece of work.
_ASKS_ONLY_FOR_AN_ANSWER = re.compile(
    r"^(?:\W*(?:and|also|so|then)\b[\s,]*)?(?:please|kindly|could you|can you|would you)?\s*(?:just\s+)?"
    r"(?:let me know|confirm|reply|respond|get back to me|advise|tell me|say)\b"
    r"(?:\s+(?:if|whether|when|what|which|that|by|as soon as|at your|your|back|to me|asap|soon)\b.*)?[\s.!?]*$", re.I)
_LEAD_IN = re.compile(r"^\W*(?:(?:and|also|separately|additionally|in addition|one more thing|oh|ps|p\.s\.|finally|"
                      r"lastly|meanwhile|by the way|on another note)\b[\s,:;-]*)*"
                      r"(?:(?:please|kindly)\s+(?:also\s+)?|(?:could|can|would|will) you (?:please |also |kindly )*|"
                      r"i need you to |we need you to |it would help (?:a lot )?if you could |"
                      r"don'?t forget to |remember to |make sure (?:you|to) |you (?:need|have) to )?", re.I)

# A statement, in so many words, that nothing is asked.
_SAYS_NO_ACTION = re.compile(
    r"\b(?:fyi|for (?:your )?info(?:rmation)?(?: only)?|no (?:further )?action (?:is |was )?(?:needed|required|necessary)|"
    r"nothing (?:is )?(?:needed|required) (?:from|of) you|no need to (?:reply|respond|do anything|act)|"
    r"no (?:reply|response) (?:is )?(?:needed|required|necessary)|just (?:an update|a heads[- ]up|to let you know|so you know)|"
    r"for the record|keeping you (?:posted|in the loop|informed)|nothing for you (?:to do|here))\b", re.I)
_ACKNOWLEDGES = re.compile(
    r"\b(?:thank you|thanks|received|got it|noted|understood|sounds good|perfect|great|will do|see you (?:then|there|on|at))\b",
    re.I)

# A reply that puts the answer off.
_DEFERS = re.compile(
    r"\bstill\b|\bnot (?:yet|quite|there)\b|\bn'?t (?:yet|have (?:it|them|an answer))\b|\bworking on\b|\bin progress\b"
    r"|\b(?:i|we)(?:'ll| will| shall| should| hope to| expect to| aim to| plan to)\b"
    r"|\bget back to you\b|\bcome back to you\b|\brevert\b|\bbear with\b|\bneed (?:more|a little|a bit|some|another)\b"
    r"|\bwaiting (?:for|on)\b|\bchasing\b|\bdelayed\b|\brunning (?:late|behind)\b|\bgive me (?:a|until|till|another)\b"
    r"|\bout of (?:the )?office\b|\baway until\b|\bon leave\b|\bsoon\b|\bshortly\b|\bin due course\b", re.I)
# ...unless the thing itself is in the message.
_DELIVERS = re.compile(
    r"\battach(?:ed|ing|ment)\b|\benclosed\b|\bhere (?:is|are|you go)\b|\bplease find\b|\bas requested\b"
    r"|\b(?:see|is|are) below\b|\bthe answer is\b", re.I)


# Text that every message from an organisation carries and nobody wrote for
# this reader.
_BOILERPLATE = re.compile(
    r"intended recipient|confidential|privileged|consider the environment|before printing|unsubscribe|disclaimer"
    r"|this (?:e-?mail|message|communication) (?:and any|is intended|may contain|was sent|has been)"
    r"|sent from my|virus(?:es)?\b|registered (?:office|in england)|company (?:number|no\.)", re.I)
_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|https?://\S+|\bwww\.\S+", re.I)
_DEADLINE_MARK = re.compile(r"\b(?:by|before|until|no later than|due)\b", re.I)
_ADDITIVE = re.compile(r"^\W*(?:(?:and\s+)?(?:also|additionally|separately|in addition|one more thing|finally|lastly|"
                       r"meanwhile|on another note|by the way)\b|(?:please|could you|can you|would you)\s+also\b)", re.I)
_CLAUSE = re.compile(r",\s*(?:and|then|also)\s+|;\s*(?:and\s+)?|\s+and\s+(?:also\s+)?(?=[a-z]+\s+(?:the|my|our|your|a|an|this|that)\b)",
                     re.I)


def sentences(text: Any) -> List[str]:
    """The message's own sentences: no greeting, nothing quoted, and nothing
    after the sign-off (a name, a job title, a legal footer)."""
    kept: List[str] = []
    for line in str(text or "").splitlines():
        if _QUOTED.match(line) or line.strip() in ("--", "-- ", "___", "---"):
            break
        if _SIGN_OFF.match(line):
            break                           # what follows the sign-off is not the message
        if not line.strip() or _GREETING.match(line):
            continue
        kept.extend(part.strip() for part in _SENTENCE.split(line) if part.strip())
    # Words in any script: a message in Arabic is still a message.
    return [s for s in kept if len(re.findall(r"[^\W\d_]{2,}", s)) >= 2 and not _BOILERPLATE.search(s)]


# Words an English sentence can hardly do without. Their absence from a
# message of some length means these rules cannot read it at all.
_FUNCTION_WORDS = frozenset("""
    the a an and or but to of in on at for from with by is are was were be been it this that these those
    i you we he she they me us my your our his her their not no yes will would can could should have has had do does
    please thanks thank as if so
""".split())


def readable(text: Any) -> bool:
    """Whether these rules can read the message. They read English; a message
    with almost none of English's small words is in another language, and
    what it asks is then UNKNOWN, never "nothing"."""
    words = re.findall(r"[^\W\d_]+", " ".join(sentences(text)).lower())
    if len(words) < 4:
        return True
    known = sum(1 for word in words if word in _FUNCTION_WORDS)
    return known / len(words) >= 0.12


def _calendar_wish(sentence: str) -> Optional[str]:
    """``new``, ``reschedule`` or ``cancel`` when the sentence is about the
    calendar: it asks to meet, move or cancel, or it asks about a day AND a
    time. Such a sentence is never recorded as a task."""
    signal = reading.meeting_signal("", sentence)
    if signal:
        return signal
    if reading._CANCEL.search(sentence):
        return "cancel"
    if reading._MOVE.search(sentence):
        return "reschedule"
    lowered = sentence.lower()
    times, _ = reading._times(lowered)
    if times and reading._days(lowered, dt.date(2026, 1, 5)) and sentence.rstrip().endswith("?") \
            and not _DEADLINE_MARK.search(sentence):
        return "new"                       # "would you have half an hour on Tuesday at 11:00?"
    if reading._MEET_VERB.search(sentence) and reading._MEETING_NOUN.search(sentence):
        return "new"
    return None


def _clauses(sentence: str) -> List[str]:
    """"approve the plan by Wednesday, and sign the mandate by Friday" is two
    requests. Split only when every part carries its own deadline."""
    body = sentence
    if ":" in sentence and _DEADLINE_MARK.search(sentence.split(":", 1)[1]):
        body = sentence.split(":", 1)[1]
    parts = [part.strip(" .") for part in _CLAUSE.split(body) if part and part.strip(" .")]
    if len(parts) >= 2 and all(_DEADLINE_MARK.search(part) for part in parts):
        return parts
    return [sentence]


def is_ask(sentence: str) -> bool:
    return bool(_ASK.search(sentence)) or sentence.rstrip().endswith("?") and bool(
        re.search(r"\b(?:you|your|we|us|our)\b", sentence, re.I))


def units(subject: Any, text: Any) -> List[Dict[str, Any]]:
    """Each sentence that asks the executive for something, with its kind:
    ``scheduling`` (it asks to meet, move or cancel), ``answer`` (it only
    asks to be answered) or ``action`` (anything else to do)."""
    found: List[Dict[str, Any]] = []
    for sentence in sentences(text):
        scheduling = _calendar_wish(sentence)
        if not scheduling and not is_ask(sentence):
            continue
        if scheduling:
            found.append({"text": sentence, "kind": "scheduling", "intent": scheduling})
            continue
        if _ASKS_ONLY_FOR_AN_ANSWER.match(sentence) or not _ASK.search(sentence):
            found.append({"text": sentence, "kind": "answer"})     # a plain question, or "let me know"
            continue
        for clause in _clauses(sentence):
            found.append({
                "text": clause, "kind": "action",
                # Clearly a separate piece of work: introduced as one more
                # thing, or carrying its own deadline.
                "separate": bool(_ADDITIVE.search(clause) or _DEADLINE_MARK.search(clause)),
                # It names an address or a link. Whoever that is, the Desk does
                # not act on it by itself.
                "names_address": bool(_ADDRESS.search(clause))})
    return found


def title_of(sentence: str) -> str:
    """A request sentence as a task title: the act, without the politeness."""
    core = _LEAD_IN.sub("", sentence.strip(), count=1).strip(" .!?;,")
    core = core or sentence.strip(" .!?;,")
    return (core[:1].upper() + core[1:])[:120]


def without(text: Any, removed: List[str]) -> str:
    """The message with some sentences taken out (another request's date must
    not be read as this request's)."""
    result = str(text or "")
    for sentence in removed:
        result = result.replace(sentence, " ")
    return result


# Saying outright that it is not there yet.
_NOT_YET = re.compile(
    r"\bstill\b|\b(?:not|n'?t)\b.{0,40}\byet\b|\bnot (?:quite|there)\b|\bworking on\b|\bin progress\b|\bbear with\b"
    r"|\bneed (?:more|a little|a bit|some|another)\b|\bwaiting (?:for|on)\b|\bchasing\b|\bdelayed\b"
    r"|\brunning (?:late|behind)\b|\bout of (?:the )?office\b|\baway until\b|\bon leave\b", re.I)
# Promising to provide it later. "I'll bring the contract" is not this: the
# verb has to be about supplying the answer.
_WILL_PROVIDE = re.compile(
    r"\b(?:i|we)(?:'ll| will| shall| should| hope to| expect to| aim to| plan to)\s+(?:\w+\s+){0,2}?"
    r"(?:have|send|get back|come back|revert|let you know|confirm|check|look into|reply|respond|update|share|"
    r"forward|follow up|be in touch|pick (?:this|it) up)\b"
    r"|\bget back to you\b|\bcome back to you\b|\bgive me (?:a|until|till|another)\b|\bsoon\b|\bshortly\b"
    r"|\bin due course\b", re.I)
# An answer in the message itself.
_ANSWERS = re.compile(
    r"\b(?:works|suits|is fine|that'?s fine|sounds good|yes|agreed|confirmed|accept(?:ed)?|declin\w+|prefer|"
    r"let'?s go with|go ahead|approved|no problem|perfect)\b|\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}\s?(?:am|pm)\b", re.I)


def is_holding_reply(text: Any) -> bool:
    """The reply says the answer is still coming, and does not contain it.

    Either it says outright that it is not there yet, or it promises to
    supply it later and gives no answer now. A reply that hands the thing
    over, or that answers (a yes, a time, "that works") while mentioning the
    future, is an answer."""
    own = " ".join(sentences(text))
    if not own or len(own.split()) > 80 or _DELIVERS.search(own):
        return False
    if _NOT_YET.search(own):
        return True
    return bool(_WILL_PROVIDE.search(own)) and not _ANSWERS.search(own)


def no_work_established(subject: Any, text: Any) -> bool:
    """True only on positive evidence that nothing is asked of the reader:
    the message says so, or it is a bare acknowledgement. A message that
    asks anything, or says something is still outstanding, is never "no work"."""
    own = sentences(text)
    if not readable(text):
        return False                        # another language: what it asks is not known
    if any(unit["kind"] in ("scheduling", "action") for unit in units(subject, text)):
        return False
    whole = f"{subject or ''}\n" + " ".join(own)
    if any(s.rstrip().endswith("?") for s in own):
        return False
    if _SAYS_NO_ACTION.search(whole):
        return True
    words = len(" ".join(own).split())
    # "Thanks, received." and nothing else. A message that says something is
    # STILL outstanding is not this, however short: someone may be waiting on
    # the reader (a holding reply counts only against a wait the Desk knows).
    if not own:
        # Nothing but a greeting and a sign-off ("Thanks, Imogen"), or truly
        # empty. A body these rules could not keep is not "nothing".
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        return all(_GREETING.match(line) or _SIGN_OFF.match(line) or len(line.split()) <= 3 for line in lines)
    return words <= 14 and bool(_ACKNOWLEDGES.search(" ".join(own))) and not _DEFERS.search(" ".join(own))
