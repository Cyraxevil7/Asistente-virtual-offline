"""Ejemplo experimental de predicción YOLO sobre una imagen remota."""

from ultralytics import YOLO

model = YOLO("yolo26n.pt")  # load a pretrained YOLO26n detection model
results = model("https://i.pinimg.com/originals/bd/6b/60/bd6b6057bbabf56940ee720b88eacea8.jpg", save=True)  # predict and save the annotated image