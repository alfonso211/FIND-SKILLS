# Modelo de Tesseract para la zona MRZ

`mrz.traineddata` es el modelo «tessdata_fast» de [DoubangoTelecom/tesseractMRZ](https://github.com/DoubangoTelecom/tesseractMRZ), con licencia BSD 3-Clause (ver `LICENSE-mrz.txt`). Está entrenado con más de 7.000 líneas MRZ reales, impresas en la fuente OCR-B de los DNI, NIE/TIE y pasaportes.

Con 240 líneas reales de ese conjunto se midió lo siguiente:

| Modelo | Líneas exactas | Acierto por carácter |
|---|---|---|
| `eng` (el de antes) | 11 % | 68,6 % |
| `mrz` | 93 % | 99,8 % |

El modelo `mrz` es además el doble de rápido. Hay que tener en cuenta que esas líneas forman parte de su entrenamiento, así que su resultado es optimista. Aun así, la diferencia con `eng` es grande.
