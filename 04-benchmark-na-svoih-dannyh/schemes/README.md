# schemes

Исходники схем статьи: `scheme.py` — копия `web/tools/scheme.py` сайта pro-llm.ru (стиль), `schemes_razbor_04.py` — три схемы разбора: карта «точность × $ за ответ», из чего складываются цена и время ответа агента, публичный бенчмарк против своего eval. Перерисовать в эту папку из корня пакета:

```bash
SCHEMES_OUT=schemes python3 schemes/schemes_razbor_04.py
```
