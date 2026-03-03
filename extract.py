import bz2
import shutil

with bz2.open('shape_predictor_68_face_landmarks.dat.bz2', 'rb') as f_in:
    with open('shape_predictor_68_face_landmarks.dat', 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)

print("Extraction complete! File saved as shape_predictor_68_face_landmarks.dat")