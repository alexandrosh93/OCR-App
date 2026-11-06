# «Ήξερες ότι;» video generator (Kouponaki)

Ξαναχτίζει το design «Ήξερες ότι;» ως motion graphics σε κάθετο βίντεο 1080×1920 (Reels/TikTok/Shorts)
με ελληνικό voiceover (edge-tts, `el-GR-NestorasNeural`):

1. **Intro**: το sticker «Ήξερες ότι;» σκάει στην οθόνη (ακτίνες, κύμα, σπίθες, ανάβει η λάμπα) και πετάει στην κορυφή.
2. **Κυρίως μέρος**: logo kouponaki.com, pill, τίτλοι (λευκό/κίτρινο/πράσινο), σήμα ομάδας (+ αστέρια),
   υπότιτλος, μασκότ, κάρτες με νούμερα που μετράνε, panel με ημερομηνία/τίτλο/κείμενο.
   Κάθε στοιχείο μπαίνει πάνω στη φωνή.
3. **End card**: sticker + kouponaki.com + «Ακολούθησε για περισσότερα».

Το φόντο είναι η φωτογραφία του γηπέδου από το post, με τα στοιχεία του design σβησμένα (inpainting).

## Νέο βίντεο

1. Βάλε το post στο `posts/` και τα cutouts (σήμα, μασκότ, PNG με διαφάνεια) στο `assets/`.
2. Φτιάξε `configs/<όνομα>.json` (δες `configs/apoel.json` και `configs/apollon.json`):
   - `lines`: οι προτάσεις της φωνής (γράψε τους αριθμούς ολογράφως, π.χ. «ένα μηδέν»)
   - `background.clear`: ορθογώνια `[x0, y0, x1, y1]` (pixel του post) που σβήνονται από το φόντο
   - κάθε στοιχείο έχει `"at": [γραμμή, δευτερόλεπτα]`: εμφανίζεται Ν δευτ. μετά την αρχή εκείνης της γραμμής
     (γραμμή 0 = αλλαγή από intro σε κυρίως μέρος)
   - στα `title` / `body` του panel, `**λέξεις**` = πράσινο highlight, `\n` = αλλαγή γραμμής
   - `photo`: πραγματική φωτογραφία που σκάει ως κάρτα στη μέση (αντικαθιστά τις κάρτες με τα νούμερα), δες `configs/ael.json`
   - `headline[].max_size`: μικρότερη γραμμή τίτλου (π.χ. «Η ΑΕΛ ΞΑΝΑ ΠΡΩΤΑΘΛΗΤΡΙΑ»)
3. Τρέξε:

```
pip install edge-tts numpy pillow opencv-python-headless
python3 make_video.py configs/<όνομα>.json ../videos/<όνομα>.mp4
python3 make_video.py configs/<όνομα>.json --preview 3,6,9,12 preview.png   # γρήγορος έλεγχος καρέ
```

Γραμματοσειρές: Fira Sans / Fira Sans Extra Condensed (SIL Open Font License, `fonts/OFL.txt`).

## «Από το μηδέν» (χωρίς έτοιμο post): `make_story.py`

Φτιάχνει ολόκληρο το βίντεο μόνο από μια **πραγματική φωτογραφία** και το **γεγονός**, σε σκηνές τύπου
τηλεοπτικού spot: ημερομηνία με «ρολόι-οδόμετρο» → η φωτό σε κάρτα + πίνακας σκορ → τίτλοι που σκάνε με
σήμα, μασκότ και κομφετί → end card. Φόντο: η ίδια η φωτογραφία, θολή και χρωματισμένη στα χρώματα της ομάδας.

Οι χρόνοι μπορούν να δένουν σε **λέξεις της φωνής**: `{"word": "πρώτη"}` = τη στιγμή που ακούγεται η λέξη
(`"edge": "end"` για το τέλος της, `"offset"` για μικροδιόρθωση). Δες `configs/anorthosis_story.json`.

```
python3 make_story.py configs/anorthosis_story.json ../videos/anorthosis_story.mp4
python3 make_story.py configs/anorthosis_story.json --preview 3,6,9,12 preview.png   # τυπώνει και τους χρόνους κάθε λέξης
```

### TikTok μορφή (`configs/anorthosis_tiktok.json`)

- `hook`: η πρώτη ερώτηση λέγεται πάνω στο intro (το intro κρατάει όσο το hook)
- λεζάντες λέξη-λέξη (σαν CapCut): σπάνε σε φυσικές φράσεις, η λέξη που ακούγεται ανάβει πράσινη
- `caption_replace`: τι γράφουν οι λεζάντες αντί γι' αυτό που διαβάζει η φωνή
  (π.χ. «δύο χιλιάδες οκτώ» → 2008, «Τσάμπιονς Λιγκ» → CHAMPIONS LEAGUE, «φόλοου» → FOLLOW)
- `emoji`: emoji δίπλα στη φράση που περιέχει τη λέξη (π.χ. «σχόλια» → 👇)
- safe zones TikTok/Reels: τίποτα σημαντικό κάτω από τα tabs, πίσω από τα κουμπιά δεξιά ή στην περιγραφή κάτω
- σκορ σε βήματα: `steps` (π.χ. 3-0 στο πρώτο ματς → 3-1 συνολικό)
- κλείνει με «ΓΡΑΨΕ ΣΤΑ ΣΧΟΛΙΑ» και χωρίς fade-out, ώστε το βίντεο να κάνει loop

## Μοντάζ «TikToker» (CapCut style): `make_tiktok.py`

Η αληθινή φωτογραφία σε όλο το πλάτος με γρήγορα cuts πάνω στις λέξεις της φωνής: punch-in zoom,
μεταβάσεις `zoomblur` / `whip` / `glitch` / `flash` / `rewind` (VHS, με PLAY/REC και ημερομηνία κάμερας),
emoji & stickers που σκάνε, τρανταγμοί και ηχητικά σε κάθε «χτύπημα», λεζάντες λέξη-λέξη.
Το βίντεο περιγράφεται ως λίστα πλάνων (`shots`) — δες `configs/anorthosis_edit.json`.

```
python3 make_tiktok.py configs/anorthosis_edit.json ../videos/anorthosis_edit.mp4
```
