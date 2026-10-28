# AnyLogic

Este proyecto trabaja con **AnyLogic 8.9**. Hay un servidor MCP con la documentación
oficial (guía de usuario + API de Java) indexada en local.

## Antes de afirmar cómo funciona algo

1. **Busca primero**: `anylogic_search("términos en inglés")` y luego
   `anylogic_read(path, heading)` para leer solo la sección que hace falta.
2. **Para código**, usa `anylogic_api("Clase.miembro")` y copia la firma exacta.
   Si el símbolo no aparece, **no existe**: no lo inventes.
3. **La documentación está en inglés**. Busca en inglés (`arrival rate`, no
   `tasa de llegada`) y responde en el idioma del usuario.
4. **Cita siempre la URL** de la página o de la clase que hayas usado.

## Herramientas disponibles

| Herramienta | Para qué |
|---|---|
| `anylogic_search(query, scope?, section?, limit?)` | punto de entrada; `scope`: `guide` o `api` |
| `anylogic_read(path, heading?, max_chars?)` | leer una página o una sección concreta |
| `anylogic_api(symbol, max_chars?)` | ficha de clase/método/campo con firma Java |
| `anylogic_api_search(query, limit?)` | buscar solo en la API |
| `anylogic_examples(query, limit?)` | ejemplos de tutoriales y modelado avanzado |
| `anylogic_toc(scope?, section?)` | mapa de secciones y paquetes |
| `anylogic_version()` | comprobar que el índice está cargado |

## Límites del entorno

Este entorno es **AnyLogic PLE 8.9.9** (Personal Learning Edition). No están
disponibles, entre otras cosas:

- exportación del modelo a Java,
- librerías propias,
- modelos por encima del límite de tamaño de PLE.

Si una respuesta depende de algo de eso, dilo explícitamente en vez de proponer una
solución que no se puede ejecutar.

## Cuándo no usar el MCP

Para dudas puramente conceptuales de simulación (qué es una cola M/M/1, cómo se calcula
la utilización) no hace falta: responde con conocimiento general. El MCP es para **la
herramienta**: bloques, propiedades, firmas, versiones y comportamiento de AnyLogic.
