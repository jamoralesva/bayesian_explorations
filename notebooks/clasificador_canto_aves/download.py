import os
import requests
import re
import csv
from typing import Dict, Any, Generator, Optional, List

class XenoCantoClient:
    """
    Cliente para interactuar con la API v3 de Xeno-canto (https://xeno-canto.org/explore/api).
    Permite la descarga de metadatos y archivos de audio asociados a grabaciones de aves.
    """
    BASE_URL = "https://xeno-canto.org/api/3/recordings"
    
    # Definición explícita de las columnas requeridas según la solicitud del usuario
    METADATA_FIELDS = [
        'gen', 'sp', 'ssp', 'grp', 'type', 'sex', 'stage', 
        'q', 'also', 'animal-seen', 'smp', 'method', 'file-name'
    ]

    def __init__(self, api_key: str):
        """
        Inicializa el cliente con la API key requerida para la versión 3.
        
        :param api_key: Clave de API provista por Xeno-canto en el perfil de usuario.
        """
        self.api_key = api_key

    def _limpiar_nombre_archivo(self, filename: str) -> str:
        """Remueve caracteres no permitidos en sistemas de archivos."""
        return re.sub(r'[\\/*?:"<>|]', "", filename)

    def buscar_grabaciones(self, query: str) -> Generator[Dict[str, Any], None, None]:
        """
        Realiza una consulta a la API y genera (yield) de forma perezosa los metadatos 
        de las grabaciones, manejando automáticamente la paginación interna.
        
        PROS: Minimiza el consumo de memoria al no cargar todas las páginas simultáneamente.
        CONTRAS: Realiza peticiones HTTP síncronas iterativas si el resultado es muy extenso.
        
        :param query: Término o etiquetas de búsqueda según la sintaxis de Xeno-canto (ej. 'cnt:brazil').
        :return: Un generador que entrega diccionarios con los metadatos de cada grabación.
        """
        pagina = 1
        while True:
            params = {
                'query': query,
                'key': self.api_key,
                'page': pagina
            }
            
            try:
                response = requests.get(self.BASE_URL, params=params, timeout=15)
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"Error en la conexión a la API de Xeno-canto: {e}")
            except ValueError:
                raise ValueError("La respuesta del servidor no contiene un JSON válido.")

            recordings = data.get('recordings', [])
            if not recordings:
                break

            for rec in recordings:
                yield rec

            # Control de fin de paginación basado en la respuesta oficial
            num_pages = int(data.get('numPages', 1))
            if pagina >= num_pages:
                break
            
            pagina += 1

    def descargar_audio(self, url_audio: str, ruta_destino: str) -> bool:
        """
        Descarga un archivo de audio específico mediante streaming de bytes.
        
        PROS: Al usar 'stream=True', evita desbordamientos de memoria RAM con archivos grandes.
        CONTRAS: Requiere manejo manual de flujos de archivos de Entrada/Salida (I/O).
        
        :param url_audio: URL provista en el campo 'file' de los metadatos de la grabación.
        :param ruta_destino: Ruta local en el disco donde se almacenará el archivo.
        :return: True si la descarga fue exitosa, False en caso contrario.
        """
        if url_audio.startswith('//'):
            url_audio = f"https:{url_audio}"

        try:
            with requests.get(url_audio, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(ruta_destino, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error al descargar el archivo desde {url_audio}: {e}")
            return False

    def guardar_metadatos_csv(self, query: str, ruta_csv: str, limite: Optional[int] = None) -> None:
        """
        Busca las grabaciones correspondientes a una consulta y almacena los campos estructurados en un CSV.
        
        PROS: Permite la recolección masiva de metadatos analíticos sin incurrir en el costo de red 
              y almacenamiento de los archivos binarios de audio (.mp3).
        CONTRAS: Depende de la consistencia de los campos devueltos por la API de Xeno-canto.
        
        :param query: Consulta de búsqueda para filtrar las grabaciones.
        :param ruta_csv: Ruta del archivo .csv de salida.
        :param limite: Cantidad máxima de registros a almacenar (opcional).
        """
        directorio = os.path.dirname(ruta_csv)
        if directorio and not os.path.exists(directorio):
            os.makedirs(directorio)

        print(f"Exportando metadatos a CSV para la consulta: '{query}'")
        contador = 0

        try:
            with open(ruta_csv, mode='w', newline='', encoding='utf-8') as archivo_csv:
                writer = csv.DictWriter(archivo_csv, fieldnames=self.METADATA_FIELDS)
                writer.writeheader()

                for grabacion in self.buscar_grabaciones(query):
                    if limite and contador >= limite:
                        print(f"Se alcanzó el límite de {limite} registros para el CSV.")
                        break

                    # Extraer solo los campos solicitados de forma segura, mapeando 'filename' a 'file-name' si aplica
                    # Nota: En el JSON de la API de Xeno-canto el campo se denomina 'file-name'
                    fila = {}
                    for campo in self.METADATA_FIELDS:
                        if campo == 'filename':
                            fila[campo] = grabacion.get('file-name', '')
                        else:
                            fila[campo] = grabacion.get(campo, '')
                    
                    # Manejo de listas embebidas en el JSON (ej: 'also' suele ser una lista)
                    if isinstance(fila.get('also'), list):
                        fila['also'] = ", ".join(fila['also'])

                    writer.writerow(fila)
                    contador += 1

            print(f"Proceso finalizado. Se exportaron {contador} registros en '{ruta_csv}'.")
        except IOError as e:
            raise RuntimeError(f"Error al escribir el archivo CSV: {e}")

    def descargar_por_busqueda(self, query: str, directorio_salida: str, limite: Optional[int] = None, exportar_csv: bool = False):
        """
        Orquesta la búsqueda de metadatos y la posterior descarga de sus respectivos audios.
        Opcionalmente genera un archivo CSV con los metadatos recolectados durante la descarga.
        
        :param query: Consulta de búsqueda para filtrar las grabaciones.
        :param directorio_salida: Carpeta local donde guardar audios y metadatos.
        :param limite: Cantidad máxima de audios a descargar (opcional).
        :param exportar_csv: Si es True, guarda un archivo metadatos.csv en el directorio de salida.
        """
        if not os.path.exists(directorio_salida):
            os.makedirs(directorio_salida)

        contador = 0
        print(f"Iniciando búsqueda con el término: '{query}'")
        
        grabaciones_procesadas: List[Dict[str, Any]] = []

        for grabacion in self.buscar_grabaciones(query):
            if limite and contador >= limite:
                print(f"Se ha alcanzado el límite impuesto de {limite} descargas.")
                break

            rec_id = grabacion.get('id')
            url_audio = grabacion.get('file')
            genero = grabacion.get('gen', 'Desconocido')
            especie = grabacion.get('sp', 'desconocida')
            
            if not url_audio:
                print(f"La grabación ID {rec_id} no posee una URL de archivo válida. Omitiendo...")
                continue

            nombre_archivo = self._limpiar_nombre_archivo(f"XC{rec_id}_{genero}_{especie}.mp3")
            ruta_completa = os.path.join(directorio_salida, nombre_archivo)

            print(f"[{contador + 1}] Descargando ID {rec_id}: {genero} {especie}...")
            
            exito = self.descargar_audio(url_audio, ruta_completa)
            if exito:
                contador += 1
                if exportar_csv:
                    grabacion['file-name'] = nombre_archivo
                    grabaciones_procesadas.append(grabacion)
                
        print(f"Proceso finalizado. Se descargaron {contador} archivos en '{directorio_salida}'.")

        # Guardar CSV consolidado si fue solicitado
        if exportar_csv and grabaciones_procesadas:
            ruta_csv = os.path.join(directorio_salida, "metadatos.csv")
            try:
                with open(ruta_csv, mode='w', newline='', encoding='utf-8') as archivo_csv:
                    writer = csv.DictWriter(archivo_csv, fieldnames=self.METADATA_FIELDS)
                    writer.writeheader()
                    for grabacion in grabaciones_procesadas:
                        fila = {c: grabacion.get(c, '') if c != 'filename' else grabacion.get('file-name', '') for c in self.METADATA_FIELDS}
                        if isinstance(fila.get('also'), list):
                            fila['also'] = ", ".join(fila['also'])
                        writer.writerow(fila)
                print(f"Metadatos guardados exitosamente en '{ruta_csv}'.")
            except IOError as e:
                print(f"No se pudo generar el CSV de metadatos: {e}")

# Ejemplo de uso:
if __name__ == "__main__":
    API_KEY_DEMO = "5b99f3dfdbebd2977b35d5adce244cd005c2e264" 
    cliente = XenoCantoClient(api_key=API_KEY_DEMO)
    
    try:
        # Opción B: Descargar audio y generar simultáneamente el CSV dentro del directorio
        cliente.descargar_por_busqueda(query='cnt:colombia', directorio_salida='aves_colombia', limite=None, exportar_csv=True)
        
    except Exception as e:
        print(f"Ocurrió un error en la ejecución: {e}")