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
3. Τρέξε:

```
pip install edge-tts numpy pillow opencv-python-headless
python3 make_video.py configs/<όνομα>.json ../videos/<όνομα>.mp4
python3 make_video.py configs/<όνομα>.json --preview 3,6,9,12 preview.png   # γρήγορος έλεγχος καρέ
```

Γραμματοσειρές: Fira Sans / Fira Sans Extra Condensed (SIL Open Font License, `fonts/OFL.txt`).
