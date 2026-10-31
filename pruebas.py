"""Entrenamiento experimental; limpia runs/ y datasets/ antes de comenzar."""

import os
import shutil
from ultralytics import YOLO

def limpiar_entrenamiento_anterior():
    """Elimina las carpetas pesadas del intento anterior sin borrar el archivo .pt"""
    # 1. Definimos las carpetas problemáticas a borrar
    carpetas_a_borrar = ["runs", "datasets"]
    
    print("🧹 Iniciando limpieza de almacenamiento...")
    for carpeta in carpetas_a_borrar:
        if os.path.exists(carpeta):
            try:
                shutil.rmtree(carpeta)
                print(f"✅ Carpeta '{carpeta}' eliminada con éxito.")
            except Exception as e:
                print(f"⚠️ No se pudo borrar '{carpeta}': {e}")
        else:
            print(f"ℹ️ La carpeta '{carpeta}' no existía, está limpio.")

if __name__ == "__main__":
    # Primero se ejecuta la limpieza preventiva
    limpiar_entrenamiento_anterior()
    
    print("\n🚀 Iniciando el entrenamiento controlado con COCO8...")
    
    # Se carga el archivo del modelo local ya existente en tu carpeta raíz
    # (Si no está, se descargará solo una vez y pesará únicamente ~6MB)
    model = YOLO("yolo11n.pt") 
    
    # Ejecutamos el entrenamiento con límites estrictos de guardado
    model.train(
        data="coco8.yaml",   # Usa el dataset compacto COCO8
        epochs=100,          # 100 épocas recomendadas
        imgsz=640,           # Tamaño de imagen estándar
        save=True,           # Guarda los resultados finales
        save_period=-1,      # ¡Importante! No crea checkpoints pesados por época
        cache=False          # Evita duplicar imágenes en memoria caché
    )
    print("\n🎉 ¡Proceso completado exitosamente y espacio optimizado!")
