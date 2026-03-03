import cv2
import detector

img = cv2.imread("test_face.jpg")
if img is None:
    print("Could not read test_face.jpg. Make sure the file exists.")
    exit()

ear_left, ear_right, detected = detector.get_eye_ear(img)
if detected:
    print(f"Left EAR: {ear_left:.3f}, Right EAR: {ear_right:.3f}")

    # Optional visualization
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = detector.detector(gray)
    for face in faces:
        x1, y1, x2, y2 = face.left(), face.top(), face.right(), face.bottom()
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        landmarks = detector.predictor(gray, face)
        for i in range(36, 48):
            x = landmarks.part(i).x
            y = landmarks.part(i).y
            cv2.circle(img, (x, y), 2, (0, 0, 255), -1)
    cv2.imshow("Test", img)
    cv2.waitKey(0)
else:
    print("No face detected")