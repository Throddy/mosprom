# Работа с git

## Правила

1. Каждый коммитит только свои пути из `STRUCTURE.md`. Поэтому изменения разных участников не пересекаются.
2. Одна задача из `PLAN.md` даёт одну ветку и один PR. Ветка живёт не дольше 2–3 часов работы.
3. В `main` напрямую не пушит никто. Вливает только Максим.
4. `core/` и `CONTRACT.md` меняются отдельным PR `contract: ...` по разделу 9 контракта.
5. Зависимости добавляются только в файл своей зоны: `ml/requirements.txt`, `backend/requirements.txt` или `frontend/package.json`.
6. В `PLAN.md` каждый правит только свой раздел, в том же PR, что и задачу.

## Первый запуск

```bash
git clone https://github.com/Throddy/mosprom.git
cd mosprom
cp .env.example .env
python -m venv .venv
```

Затем нужно активировать `.venv` и выполнить `pip install -r requirements.txt`.

## Цикл задачи

1. Создать ветку от свежего `main`:

```bash
git switch main
git pull
git switch -c ml/ML-1-onnx
```

Имя ветки: `<зона>/<номер задачи>-<коротко>`. Зоны: `ml`, `backend`, `frontend`.

2. Закоммитить работу. Добавлять только свои пути:

| Участник | Команда |
|---|---|
| Аня | `git add ml/ configs/models.yaml notebooks/ reports/ PLAN.md` |
| Максим | `git add backend/ logic/ core/ scripts/ configs/cameras.yaml PLAN.md` |
| Никитос | `git add frontend/ README.md docs/ data/test_set/ PLAN.md` |

Корневые файлы своей зоны (`.gitignore`, `.env.example`, `requirements.txt`, `STRUCTURE.md`, `GIT.md`, `data/demo.mp4`) Максим добавляет по имени.

```bash
git commit -m "ml: экспорт yolov8n-pose в onnx (ML-1)"
```

Команды `git add .` и `git add -A` не используются.

3. Перед PR подтянуть `main` в ветку:

```bash
git fetch origin
git merge origin/main
git push -u origin ml/ML-1-onnx
```

4. Открыть PR в `main`. Заголовок оформляется как коммит, тело по шаблону:

```
Что: экспорт yolov8n-pose и yolov8n в onnx, бэкенд onnx
Задача: ML-1
Как проверено: create_detector("onnx") на 20 кадрах, smoke.py проходит
```

5. После вливания удалить ветку и вернуться к шагу 1:

```bash
git switch main
git pull
git branch -d ml/ML-1-onnx
```

## Конфликт

Конфликт возникает только в общих файлах. Его решает автор PR в своей ветке:

```bash
git fetch origin
git merge origin/main
# поправить файлы с пометками <<<<<<< и >>>>>>>
git add <файлы>
git commit
git push
```

Если конфликт в чужой зоне, ничего не править и написать владельцу зоны.

## Максим: вливание

1. Проверить, что PR меняет только файлы зоны автора.
2. Запустить `python scripts/smoke.py` на ветке PR.
3. Влить через «Squash and merge». Ветка в `main` превращается в один коммит.
4. Удалить ветку.

Готовые PR вливаются не реже раза в 2 часа. За час до каждого чек-поинта Максим вливает всё готовое, после этого в `main` принимаются только исправления.

## Не коммитим

Видео, веса, программы TPU, `.env`, `.venv/`, `node_modules/`, `frontend/dist/`, снимки событий. Полный список приведён в `.gitignore` из `STRUCTURE.md`. Если файл попал в коммит, его нужно убрать до PR:

```bash
git rm --cached <файл>
git commit -m "ml: удалён лишний файл (ML-1)"
```
