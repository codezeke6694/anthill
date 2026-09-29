# Builds the six flow-chart SVGs on one grid, so boxes, diamonds and arrows
# line up the same way in every figure.
import html

def esc(s): return html.escape(s, quote=True)

class Fig:
    def __init__(self, w, h, label):
        self.w, self.h, self.label, self.parts = w, h, label, []
    def box(self, x, y, w, title, sub="", kind="b", h=48):
        self.parts.append(f'<rect class="{kind}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>')
        cx = x + w / 2
        if sub:
            self.parts.append(f'<text class="t" x="{cx}" y="{y+20}" text-anchor="middle">{esc(title)}</text>')
            self.parts.append(f'<text class="s" x="{cx}" y="{y+36}" text-anchor="middle">{esc(sub)}</text>')
        else:
            self.parts.append(f'<text class="t" x="{cx}" y="{y+h/2+4.5}" text-anchor="middle">{esc(title)}</text>')
    def diamond(self, cx, cy, hw, hh, l1, l2=""):
        pts = f"{cx},{cy-hh} {cx+hw},{cy} {cx},{cy+hh} {cx-hw},{cy}"
        self.parts.append(f'<polygon class="d" points="{pts}"/>')
        if l2:
            self.parts.append(f'<text class="t" x="{cx}" y="{cy-2}" text-anchor="middle">{esc(l1)}</text>')
            self.parts.append(f'<text class="t" x="{cx}" y="{cy+13}" text-anchor="middle">{esc(l2)}</text>')
        else:
            self.parts.append(f'<text class="t" x="{cx}" y="{cy+4.5}" text-anchor="middle">{esc(l1)}</text>')
    def arrow(self, pts, label="", lx=None, ly=None, kind="e", anchor="middle"):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        mk = "flow-no" if kind == "e no" else ("flow-ok" if kind == "e ok" else "flow-arrow")
        self.parts.append(f'<path class="{kind}" d="{d}" marker-end="url(#{mk})"/>')
        if label:
            cls = "l no" if "no" in kind.split() else ("l ok" if "ok" in kind.split() else "l")
            self.parts.append(f'<text class="{cls}" x="{lx}" y="{ly}" text-anchor="{anchor}">{esc(label)}</text>')
    def svg(self):
        return (f'<svg viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{esc(self.label)}">'
                + "".join(self.parts) + "</svg>")

figs = []

# 1 — a new agent picks up a task
f = Fig(880, 180, "A new agent runs where to learn what to work on, orient for the whole picture, then start for a card; if the card points at the right place it reads and changes the code, otherwise it tries the next candidate.")
f.box(10, 16, 130, "New chat", "knows nothing")
f.box(175, 16, 140, "anthill where", "what to work on")
f.box(350, 16, 150, "anthill orient", "the whole hill, one page")
f.box(535, 16, 165, "anthill start \"task\"", "a card for the best file")
f.arrow([(140, 40), (173, 40)]); f.arrow([(315, 40), (348, 40)]); f.arrow([(500, 40), (533, 40)])
f.arrow([(630, 64), (630, 98)])
f.diamond(630, 130, 72, 30, "Right place?")
f.arrow([(702, 130), (728, 130)], "yes", 715, 122, "e ok")
f.box(730, 106, 140, "Read it, change it", "the card's tests prove it", "ok")
f.arrow([(558, 130), (512, 130)], "no", 535, 122, "e no")
f.box(330, 106, 180, "Look at the next one", "or follow a pathway")
f.arrow([(420, 106), (420, 88), (585, 88), (585, 66)], "try again", 500, 82)
figs.append(("new-agent", "A new agent picks up a task",
  "Somebody opens a new chat and asks: “make the Home map markers bigger.”",
  f.svg(),
  "The agent never searches blind. Its rules send it to where first, for what is being worked on; then the whole picture; then it asks Anthill where the task lives. The card is a starting point: if it isn't the deciding line, the agent follows the pathways the card lists."))

# 2 — a change, end to end
f = Fig(880, 250, "A change is committed; the guard refuses a commit on main or with a secret or junk file; a saved commit triggers the after-commit hook, which redraws the map and lists what was left undone; if anything is, the keeper tidies it in the background and anything still open is kept for the next session.")
f.box(10, 16, 120, "Change the code")
f.box(165, 16, 120, "git commit")
f.arrow([(130, 40), (163, 40)])
f.arrow([(285, 40), (323, 40)])
f.diamond(390, 40, 65, 30, "Safe to", "commit?")
f.arrow([(390, 70), (390, 98)], "no", 400, 88, "e no", "start")
f.box(310, 100, 160, "Refused", "on main · secret · junk", "no")
f.arrow([(310, 124), (225, 124), (225, 66)], "fix, retry", 268, 118, "e no")
f.arrow([(455, 40), (488, 40)], "yes", 471, 32, "e ok")
f.box(490, 16, 150, "Commit saved", "on this laptop only")
f.arrow([(640, 40), (673, 40)])
f.box(675, 16, 195, "After-commit hook", "redraws the map · runs upkeep")
f.arrow([(772, 64), (772, 98)])
f.diamond(772, 130, 65, 30, "Anything", "left undone?")
f.arrow([(772, 160), (772, 188)], "no", 782, 178, "e ok", "start")
f.box(707, 190, 130, "Nothing to tidy", kind="ok")
f.arrow([(707, 130), (672, 130)], "yes", 690, 122)
f.box(470, 106, 200, "Keeper starts, in background", "the agent carries on with you")
f.arrow([(570, 154), (570, 188)])
f.box(470, 190, 200, "Glossary and notes fixed", "test gaps suggested, unsigned")
f.arrow([(470, 214), (432, 214)])
f.box(230, 190, 200, "Still open? It's kept", "the next session sees it first")
figs.append(("change", "A change, from edit to tidy-up",
  "The agent makes the markers bigger and commits.",
  f.svg(),
  "Two checks happen without anyone asking. Before the commit, a guard refuses anything unsafe. After it, the map redraws itself and a helper does the paperwork in the background, so you get your change straight away."))

# 3 — pushing
f = Fig(880, 160, "When work is ready, the agent pushes only if the owner asked for that push; the push goes through with the owner's prefix, and is refused if it would rewrite history others already have.")
f.box(10, 16, 140, "Work is ready", "commits on a branch")
f.arrow([(150, 40), (178, 40)])
f.diamond(250, 40, 70, 30, "Did the owner", "ask for this push?")
f.arrow([(250, 70), (250, 98)], "no", 260, 88, "e no", "start")
f.box(170, 100, 160, "Says what's ready", "and waits for you", "no")
f.arrow([(320, 40), (353, 40)], "yes", 336, 32, "e ok")
f.box(355, 16, 170, "Push", "ANTHILL_OWNER=1 git push")
f.arrow([(525, 40), (553, 40)])
f.diamond(620, 40, 65, 30, "Rewrites", "history?")
f.arrow([(620, 70), (620, 98)], "yes", 630, 88, "e no", "start")
f.box(540, 100, 160, "Refused", "force push blocked", "no")
f.arrow([(685, 40), (718, 40)], "no", 701, 32, "e ok")
f.box(720, 16, 150, "On GitHub", "backed up and shared", "ok")
figs.append(("push", "Pushing to GitHub",
  "The agent has three commits ready on a branch.",
  f.svg(),
  "Pushing is always your act. An agent that wasn't asked says what's ready and stops. A push without your prefix is refused by the hook, and so is one that would overwrite what others already have."))

# 4 — a task that only reads
f = Fig(880, 160, "A task that only researches commits nothing, so no hook fires; before finishing, the agent asks whether anything is on the list or whether it learned something; if so the keeper writes it down unconfirmed, and it becomes trusted when the owner signs it.")
f.box(10, 16, 150, "Research or measure", "nothing to commit")
f.arrow([(160, 40), (193, 40)])
f.box(195, 16, 150, "No commit, no hook", "nothing reminds it")
f.arrow([(345, 40), (378, 40)])
f.box(380, 16, 175, "Before finishing", "list open? learned something?")
f.arrow([(555, 40), (588, 40)])
f.diamond(660, 40, 70, 30, "Anything", "worth keeping?")
f.arrow([(730, 40), (758, 40)], "no", 744, 32)
f.box(760, 16, 110, "Done")
f.arrow([(660, 70), (660, 98)], "yes", 670, 88, "e", "start")
f.box(560, 100, 200, "Keeper writes it down", "glossary or notes, unconfirmed")
f.arrow([(560, 124), (502, 124)])
f.box(300, 100, 200, "You read it and sign it", "now every agent trusts it", "ok")
figs.append(("reads", "A task that only reads",
  "An agent spends an hour measuring the news and learns that you call “gemini-sweep” the web sweep.",
  f.svg(),
  "No code changed, so no commit and no hook. The rules ask the agent two questions before it stops, so what it learned is written down instead of vanishing with the chat."))

# 5 — through the board
f = Fig(880, 240, "A unit is claimed and built inside its own files; the gate checks files, tests, map and review; a pass closes it with work done, a failure is fixed and re-gated, and a unit that cannot be finished is escalated to the owner.")
f.box(10, 16, 130, "work next", "claims one unit")
f.arrow([(140, 40), (173, 40)])
f.box(175, 16, 150, "Build inside its files", "and nowhere else")
f.arrow([(325, 40), (343, 40)])
f.box(345, 16, 140, "work gate", "files · tests · map · review")
f.arrow([(485, 40), (498, 40)])
f.diamond(570, 40, 70, 30, "All four", "pass?")
f.arrow([(640, 40), (673, 40)], "yes", 656, 32, "e ok")
f.box(675, 16, 195, "work done", "only a passing gate closes it", "ok")
f.arrow([(570, 70), (570, 98)], "no", 580, 88, "e no", "start")
f.box(470, 100, 200, "Fix and re-gate", "the exit code says what", "no")
f.arrow([(470, 124), (250, 124), (250, 66)], "fix", 360, 118, "e no")
f.arrow([(570, 148), (570, 178)], "can't finish", 580, 168, "e", "start")
f.box(470, 180, 200, "Escalate to the owner", "reopened once the cause is fixed")
figs.append(("board", "A piece of work through the board",
  "A planned piece of work: “draw the chain as four stops”.",
  f.svg(),
  "The agent never decides it is finished. The gate does: the unit stayed inside its files, its tests pass, the map is true, and it was reviewed. Anything else goes back for a fix, or to you."))

# 6 — code changes under a note
f = Fig(880, 175, "When code a written rule cites changes shape, its fingerprint differs and upkeep lists the rule; the keeper reads the code and either fixes the citation if the rule is still true or rewrites the rule if not, and the note stays unconfirmed until the owner reads it.")
f.box(10, 16, 150, "A function changes", "renamed, new inputs")
f.arrow([(160, 40), (193, 40)])
f.box(195, 16, 140, "Commit")
f.arrow([(335, 40), (368, 40)])
f.box(370, 16, 170, "Fingerprint differs", "the note may be wrong now")
f.arrow([(540, 40), (573, 40)])
f.box(575, 16, 150, "Upkeep lists it", "keeper is sent")
f.arrow([(650, 64), (650, 98)])
f.diamond(650, 130, 75, 30, "Rule still", "true?")
f.arrow([(725, 130), (748, 130)], "yes", 736, 122, "e ok")
f.box(750, 106, 120, "Fix the citation", kind="ok")
f.arrow([(575, 130), (532, 130)], "no", 553, 122)
f.box(330, 106, 200, "Rewrite the rule", "and note what changed")
figs.append(("stale-note", "When code changes under a written note",
  "Someone renames the function a rule is about: “the 650 km cut-off must never be lowered”.",
  f.svg(),
  "Anthill notices because the shape of the code changed, not because anyone remembered. The keeper checks the rule against the new code and fixes whichever is out of date. It stays unconfirmed until you've read it."))

# 7 — carry on
f = Fig(880, 175, "Told only carry on, the agent runs where, which also flags pages that fell behind; it leaves alone files another session is editing; if the next step waits on the owner it asks with a recommendation and does it once answered, otherwise it does the next step.")
f.box(10, 16, 120, "\u201ccarry on\u201d", "nothing else said")
f.arrow([(130, 40), (163, 40)])
f.box(165, 16, 160, "anthill where", "all work · stale pages flagged")
f.arrow([(325, 40), (353, 40)])
f.diamond(425, 40, 70, 30, "Being edited", "right now?")
f.arrow([(425, 70), (425, 98)], "yes", 435, 88, "e no", "start")
f.box(335, 100, 180, "Leave those files alone", "another chat is on them", "no")
f.arrow([(495, 40), (533, 40)], "no", 514, 32)
f.diamond(610, 40, 75, 30, "Next step needs", "the owner?")
f.arrow([(610, 70), (610, 98)], "yes", 620, 88, "e", "start")
f.box(515, 100, 190, "Ask, with a recommendation", "and wait for the answer")
f.arrow([(685, 40), (718, 40)], "no", 701, 32, "e ok")
f.box(720, 16, 150, "Do the next step", "the page says what, where", "ok")
f.arrow([(705, 124), (795, 124), (795, 66)], "answered", 750, 118, "e ok")
figs.append(("carry-on", "\u201cCarry on\u201d",
  "You open a new chat and type two words.",
  f.svg(),
  "Every chat reads the same page, so none of them starts from its own guess. The page says what is next, what waits on you, and what another chat is editing this minute. Tested with a fresh agent told nothing else: it chose the right work and stopped at the decision that was yours."))

# 8 — installing in a new project
f = Fig(880, 175, "anthill install switches on the guards, the keeper and the rules; if there is code it surveys it at once: the map, a starting score from past commits, the largest code no page explains, and recent work with no page; the first chat then answers the charter questions and hands the lists to the keeper.")
f.box(10, 16, 130, "anthill install", "one command")
f.arrow([(140, 40), (173, 40)])
f.box(175, 16, 170, "Guards, keeper, rules", "switched on")
f.arrow([(345, 40), (378, 40)])
f.diamond(450, 40, 70, 30, "Any code", "yet?")
f.arrow([(450, 70), (450, 98)], "no", 460, 88, "e", "start")
f.box(360, 100, 180, "Plan the areas first", "nothing to survey yet")
f.arrow([(520, 40), (553, 40)], "yes", 536, 32, "e ok")
f.box(555, 16, 150, "Survey, at once", "map · score · backlog · work")
f.arrow([(705, 40), (738, 40)])
f.box(740, 16, 130, "First chat", "charter questions")
f.arrow([(805, 64), (805, 98)])
f.box(690, 100, 180, "Keeper writes the pages", "from the survey's lists", "ok")
figs.append(("install", "Installing Anthill in a new project",
  "A new project with some history, and nobody has written anything down.",
  f.svg(),
  "Anthill knows the project before the install finishes: every part of the code and how it connects, how often it can find the right file for a past task, what most needs a written note, and which branches have work on them. The notes themselves need an agent, so the first chat hands those lists to the keeper."))

out = []
IO = {'new-agent': '<b>Reads</b> the work pages (<code>.anthill/knowledge/work/</code>), the map (<code>.anthill/build/maps/codebase.json</code>), the written rules and glossary (<code>.anthill/knowledge/</code>) and the live code. <b>Writes</b> nothing: every step here only reads.', 'change': '<b>The guard reads</b> the settings (<code>.anthill/anthill.config.json</code>). <b>The hook writes</b> the map (<code>.anthill/build/maps/codebase.json</code>) and the open list (<code>.anthill/build/upkeep.json</code>). <b>The keeper writes</b> the glossary, notes and work pages (<code>.anthill/knowledge/</code>). The code itself lands in git, on this laptop.', 'push': '<b>The guard reads</b> the settings (<code>.anthill/anthill.config.json</code>) and the commits being sent. <b>Writes</b> nothing in Anthill; the commits go to GitHub.', 'reads': '<b>The keeper writes</b> the glossary (<code>.anthill/knowledge/GLOSSARY.md</code>) or a notes page (<code>.anthill/knowledge/modules/</code>), marked unconfirmed. <b>You sign</b> it by filling <code>intent_attested_by</code> at the top of the page.', 'board': "<b>The board lives in</b> <code>.anthill/build/work/&lt;project&gt;/</code>: the plan (<code>contract.json</code>), each unit's state (<code>state/</code>) and its brief (<code>briefs/</code>). <b>The gate reads</b> the map and the notes; a review is recorded in <code>.anthill/audits/</code>; an escalation is written to <code>escalations/</code>.", 'stale-note': '<b>Reads</b> the fingerprints recorded in the map and the citations on the notes pages (<code>.anthill/knowledge/modules/</code>). <b>The keeper writes</b> the corrected page.', 'carry-on': "<b>Reads</b> the work pages, your decisions and the traps (<code>.anthill/knowledge/work/</code>, <code>decisions/</code>, <code>TRAPS.md</code>), the board, and git's record of commits and uncommitted changes. <b>Writes</b> nothing.", 'install': '<b>Writes</b> the rules every agent reads (<code>CLAUDE.md</code>, <code>AGENTS.md</code>), the keeper (<code>.claude/agents/anthill-keeper.md</code>), which files agents may not edit (<code>.claude/settings.json</code>), the settings (<code>.anthill/anthill.config.json</code>), the charter (<code>CONSTITUTION.md</code>) and the three git hooks (<code>.git/hooks/</code>). <b>The survey writes</b> the map.'}

# 9 — where everything is kept
f = Fig(880, 392, "Who reads and writes what: install writes the rules files, the settings and the map; a commit's guard reads the settings and its hook writes the map and the open list; the keeper reads the open list and the code and writes the knowledge; where reads the knowledge, the board and git; orient and start read the map, the knowledge and the live code.")
L = [("You run install", 16), ("An agent commits", 100), ("After a commit", 184), ("A new chat", 250), ("Any task", 316)]
P = [("install", "rules · settings · survey", 16), ("guard, then hook", "check · map · upkeep", 100),
     ("the keeper", "in the background", 184), ("anthill where", "what to work on", 250),
     ("orient · start", "the picture · the card", 316)]
S = [("Rules files", "CLAUDE.md · AGENTS.md · keeper", 12), ("Settings", "anthill.config.json", 64),
     ("The map", "build/maps/codebase.json", 116), ("The open list", "build/upkeep.json", 168),
     ("The job board", "build/work/<project>/", 220), ("Knowledge", "work · decisions · glossary · notes", 272),
     ("Code and git history", "the project itself", 324)]
for (t, y) in L:
    f.box(10, y, 150, t)
for (t, sub, y) in P:
    f.box(330, y, 190, t, sub)
for (t, y), (_, _, py) in zip(L, P):
    f.arrow([(160, y + 24), (328, py + 24)])
for (t, sub, y) in S:
    f.box(660, y, 210, t, sub, "st", h=44)
def sy(i, k=0):            # a store's left edge, spread so arrowheads never stack
    return S[i][2] + 22 + k * 7
def link(p, i, kind, k=0):
    f.arrow([(520, P[p][2] + 24), (658, sy(i, k))], kind=kind)
link(0, 0, "e w", -1); link(0, 1, "e w", -1); link(0, 2, "e w", -2)
link(1, 1, "e r", 1); link(1, 2, "e w", 0); link(1, 3, "e w", -1); link(1, 6, "e r", -2)
link(2, 3, "e r", 1); link(2, 5, "e w", -2); link(2, 6, "e r", -1)
link(3, 4, "e r", 0); link(3, 5, "e r", 0); link(3, 6, "e r", 0)
link(4, 2, "e r", 2); link(4, 5, "e r", 2); link(4, 6, "e r", 1)
figs.append(("kept", "Where everything is kept",
  "Every box on the charts above reads or writes one of these.",
  f.svg(),
  "Solid arrows write, dashed arrows read. Only three things ever write to Anthill's records: the install, the hooks that run on a commit, and the keeper. Every command an agent runs to find its way only reads, which is why a cold agent can run them without asking."))
IO["kept"] = "<b>All of it</b> lives in the project folder: the rules files at the top, <code>.claude/</code> for the keeper and the edit rules, and <code>.anthill/</code> for everything else. <code>.anthill/build/</code> is redrawn by Anthill and never edited by hand; <code>.anthill/knowledge/</code> is written by the keeper and signed by you."

for fid, title, scenario, svg, caption in figs:
    out.append(f'''        <article class="entry flow" id="flow-{fid}">
          <h3>{esc(title)}</h3>
          <p class="gist">{esc(scenario)}</p>
          <figure>
            <div class="scroll">{svg}</div>
            <figcaption>{esc(caption)}</figcaption>
          </figure>
          {('<p class="io"><span>Kept in</span> ' + IO[fid] + '</p>') if fid in IO else ''}
        </article>
''')
open("flows.html", "w").write("".join(out))
print(len(figs), "figures")
