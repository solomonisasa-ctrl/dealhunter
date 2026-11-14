"""Builds lm.json, the prediction model the app loads.

Inputs: corpus.txt (everyday sentences in his voice, next to this script) and a
word-frequency list (word count per line, e.g. the OpenSubtitles en_50k list) for
spelling coverage. Usage: python build_lm.py <freq_list> <out_json>
"""
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEX_SIZE = 30000

# Words never offered as predictions
BLOCK = set("""
fuck fucking fucked fucker fuckin motherfucker motherfucking shit shitty bullshit bitch bitches bastard asshole ass
dick cock pussy cunt whore slut damn goddamn goddamnit hell crap piss pissed nigga nigger fag faggot retard retarded
jesus christ sex sexy porn penis vagina boobs tits dildo horny
""".split())

# Split contractions in the subtitle list ("don" + "'t") are rebuilt into whole words
NOT_STEMS = "don didn doesn isn wasn wouldn haven couldn aren ain shouldn weren hasn hadn".split()
SHARES = {
    "'s": {"it's": .25, "that's": .15, "what's": .08, "he's": .07, "she's": .05, "there's": .05, "let's": .05, "here's": .02, "who's": .01, "where's": .01},
    "'re": {"you're": .5, "we're": .25, "they're": .2},
    "'ll": {"i'll": .4, "you'll": .2, "we'll": .15, "he'll": .08, "they'll": .07, "she'll": .05, "it'll": .05},
    "'ve": {"i've": .45, "you've": .2, "we've": .15, "they've": .1, "could've": .03, "would've": .03, "should've": .03},
    "'d": {"i'd": .35, "you'd": .2, "he'd": .1, "we'd": .1, "they'd": .08, "she'd": .07},
}
CAPS = {w.lower(): w for w in """
I I'm I'll I've I'd TV iPad iPhone FaceTime OK God Christmas Easter Thanksgiving Halloween Ramadan Eid
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August
September October November December America American Mexico Mexican Texas Argentina Barcelona Messi Spain Spanish
English Arabic Muslim Christian Pepsi Coke McDonald's Arby's Whataburger Walmart Target Netflix YouTube Amazon
Alexa Mom Dad Spurs Barca Inshallah Alhamdulillah Mashallah Habibi Habibti Yalla
""".split()}
# Words that are capitalized only when they mean the name (Mom, Dad, May...) stay lowercase as plain words
SOFT_CAPS = {"may", "march", "mom", "dad", "target", "spurs", "god"}


def read_corpus():
    sents = []
    for line in (HERE / "corpus.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        n = 1
        m = re.search(r"\s+x(\d+)$", line)
        if m:
            n = int(m.group(1))
            line = line[: m.start()]
        sents.append((line, n))
    return sents


def tokens(text):
    return re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", text)


def read_lexicon(path):
    counts = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        w, c = parts[0], int(parts[1])
        counts[w] = counts.get(w, 0) + c
    lex = Counter()
    not_total = 0
    for stem in NOT_STEMS:
        c = counts.get(stem, 0)
        lex[stem[:-1] + "n't"] += c
        not_total += c
    # can't and won't arrive as "can"/"won" + "'t"; give them what's left of the 't count
    rest = max(0, counts.get("'t", 0) - not_total)
    lex["can't"] += int(rest * 0.75)
    lex["won't"] += int(rest * 0.25)
    lex["i'm"] += counts.get("'m", 0)
    for suf, share in SHARES.items():
        for w, s in share.items():
            lex[w] += int(counts.get(suf, 0) * s)
    for w, c in counts.items():
        if w in NOT_STEMS or w.startswith("'"):
            continue
        if not re.fullmatch(r"[a-z]+(?:'[a-z]+)?", w):
            continue
        if len(w) == 1 and w not in ("a", "i"):
            continue
        if w in BLOCK:
            continue
        lex[w] += c
    return lex


def main():
    freq_path, out_path = sys.argv[1], sys.argv[2]
    corpus = read_corpus()
    lex = read_lexicon(freq_path)

    bi = defaultdict(Counter)
    tri = defaultdict(Counter)
    uni = Counter()
    disp = {}
    for text, n in corpus:
        toks = tokens(text)
        for i, t in enumerate(toks):
            k = t.lower()
            if i > 0 and t != k and k not in SOFT_CAPS:
                disp[k] = t
            c1 = "^" if i == 0 else toks[i - 1].lower()
            c2 = None if i == 0 else ("^ " + toks[0].lower() if i == 1 else toks[i - 2].lower() + " " + toks[i - 1].lower())
            bi[c1][k] += n
            if c2:
                tri[c2][k] += n
            uni[k] += n
    for k, v in CAPS.items():
        if k not in SOFT_CAPS:
            disp[k] = v

    # Corpus words always make it into the lexicon
    top = [w for w, _ in lex.most_common(LEX_SIZE)]
    have = set(top)
    for w in uni:
        if w not in have:
            top.append(w)
            lex[w] = max(lex.get(w, 0), 2000)
            have.add(w)

    def pack(counter):
        return " ".join(f"{w} {c}" for w, c in counter.most_common())

    out = {
        "v": 1,
        "lex": "\n".join(f"{w} {lex[w]}" for w in top),
        "uni": pack(uni),
        "bi": {k: pack(v) for k, v in bi.items()},
        "tri": {k: pack(v) for k, v in tri.items()},
        "disp": disp,
        "sents": [[t, n] for t, n in corpus],
    }
    Path(out_path).write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print("lexicon", len(top), "corpus sentences", len(corpus), "tokens", sum(uni.values()),
          "bigram contexts", len(bi), "trigram contexts", len(tri), "bytes", Path(out_path).stat().st_size)


if __name__ == "__main__":
    main()
