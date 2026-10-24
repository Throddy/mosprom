# Видео для быстрого запуска

Владелец: Максим. Копии 720p, 10 кадров/с, без звука, сжатые `scripts/transcode.py` и `scripts/make_reel.py`. Нужны, чтобы систему и демо-стенд можно было запустить сразу после `git clone`.

| Файл | Сцена | Длительность, с | Нарушение по разметке dev |
|---|---|---|---|
| `normal_sit_stand.mp4` | человек сидит, встаёт и идёт к камере | 12.2 | нет |
| `fall.mp4` | человек идёт по коридору и падает | 33.2 | `fall` 6.5–19.5 с |
| `danger_zone.mp4` | человек заходит в зону у двери, отмеченную на полу | 24.8 | `danger_zone` 7.5–18.0 с |
| `proximity.mp4` | цех, пешеход у вил погрузчика | 12.2 | `proximity` 0.0–3.0 с |
| `running.mp4` | человек бежит к камере | 18.3 | `running` 7.5–12.5 с |
| `reel.mp4` | ролик демо-стенда: `normal_sit_stand`, `fall`, `normal_sit_stand`, `proximity`, `normal_sit_stand`, `running`, между сценами 1 с чёрного | 105.3 | по сценам |

Происхождение:

- `normal_sit_stand`, `fall`, `danger_zone`, `running` сняты командой, участники согласны на публикацию.
- `proximity` — видео склада с погрузчиком из набора настройки команды.
- Исходники 4K лежат в общей папке команды по ссылке из `README.md`, раздел «Данные». Метрики и подбор порогов считались на исходниках, а не на этих копиях.

Пересобрать:

```bash
python scripts/transcode.py --src data/videos/dev --dst data/videos/demo
python scripts/make_reel.py --dst data/videos/demo/reel.mp4 data/videos/demo/normal_sit_stand.mp4 data/videos/demo/fall.mp4 data/videos/demo/normal_sit_stand.mp4 data/videos/demo/proximity.mp4 data/videos/demo/normal_sit_stand.mp4 data/videos/demo/running.mp4
```
