# «Ήξερες ότι;» video generator (Kouponaki)

Παίρνει ένα post «Ήξερες ότι;» και βγάζει κάθετο βίντεο 1080×1920 (Reels/TikTok/Shorts):

1. Animated intro από το sticker «Ήξερες ότι;» (`assets/hxeres_logo.png`) με συνθετικά ηχητικά.
2. Το post με κινήσεις κάμερας που ακολουθούν ελληνικό voiceover (edge-tts, `el-GR-NestorasNeural`).
3. End card με το logo kouponaki.com (`assets/kouponaki_logo.png`).

## Νέο βίντεο

1. Βάλε το post στο `posts/`.
2. Φτιάξε `configs/<όνομα>.json` (δες `configs/apoel.json`): `lines` = οι προτάσεις της φωνής,
   `shots` = μία κίνηση κάμερας ανά πρόταση (`[cx, cy, zoom]` σε pixel του post, zoom 1 = όλο το πλάτος),
   προαιρετικό `callout` = περιοχή του post που «σκάει» μπροστά.
3. Τρέξε:

```
pip install edge-tts numpy pillow
python3 make_video.py configs/<όνομα>.json ../videos/<όνομα>.mp4
python3 make_video.py configs/<όνομα>.json --preview 0.6,3,6,10 preview.png   # γρήγορος έλεγχος καρέ
```

Γράψε τους αριθμούς ολογράφως στις προτάσεις (π.χ. «ένα μηδέν») για σωστή προφορά.
