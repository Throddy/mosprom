import math
import statistics

# Дата обращения ко всем источникам: 24.10.2026. Полные ссылки: reports/economics.md.

# reports/benchmarks.json: чистое время ускорителя, pose + det, 91,1 мс на кадр.
ACCELERATOR_FPS = 10.98
# Допущение: частота анализа каждой камеры, кадров/с (обоснование в reports/economics.md).
CAMERA_FPS = 3
SCENARIOS = {"мастерская": 5, "цех": 50}

# Курс ЦБ РФ на 24.10.2026, ₽ за доллар: cbr.ru/scripts/XML_daily.asp.
USD_RUB = 80.5381
# Hailo-8 M.2, 26 TOPS, $179.99: waveshare.com/hailo-8.htm.
HAILO8_USD = 179.99
# NVIDIA Jetson Orin NX 16GB, модуль, $999: rcdrone.top.
ORIN_NX_USD = 999.0
# Допущение: цена платы LinQ — верхняя граница диапазона аналогов, округление до тысяч.
BOARD_RUB = round(ORIN_NX_USD * USD_RUB, -3)
# Цены платы для расчёта чувствительности, ₽.
BOARD_PRICES_RUB = (80_000, 160_000, 300_000)

# Сервер для бэкенда, архива и интерфейса, б/у, с НДС: serverflow.ru, раздел «Серверы для
# видеонаблюдения». HP DL380 Gen9 2×Xeon E5-2697Av4 — для 5 камер; Supermicro 6019U 1U
# 2×Xeon Gold 6148 — для 50 камер.
SERVER_RUB = {"мастерская": 300_000, "цех": 549_200}
# Допущение: часы инженера на внедрение — 8 ч на площадку и 2 ч на камеру (зоны и правила).
DEPLOY_HOURS_BASE = 8
DEPLOY_HOURS_PER_CAMERA = 2
# Допущение: ставка инженера-интегратора, ₽/ч.
ENGINEER_RUB_PER_HOUR = 2_500

# hh.ru, Москва, «оператор видеонаблюдения», вакансии с месячной зарплатой, 24.10.2026.
# Вилка → середина, «от» или «до» → указанная сумма; True — сумма указана «на руки».
OPERATOR_SALARIES_RUB = [(135_000, True), (100_000, True), (90_000, True), (75_000, True),
                         (109_607, False), (52_000, False), (109_607, False),
                         (109_607, False), (105_000, True), (70_000, True)]
# Доля суммы на руки в сумме до вычета: НДФЛ 13 %, НК РФ, ст. 224.
NET_SHARE = 0.87
# Страховые взносы работодателя, единый тариф: НК РФ, ст. 425.
INSURANCE_RATE = 0.30
# Часов в году на круглосуточном посту и норма часов на ставку при 40-часовой неделе в 2026 г.:
# производственный календарь 2026, buh.ru.
POST_HOURS_PER_YEAR = 24 * 365
NORM_HOURS_2026 = 1972
# Допущение: один оператор без системы ведёт от 25 до 16 камер; источник нормы не найден.
CAMERAS_PER_OPERATOR = (25, 16)
# Допущение: с системой один оператор ведёт вдвое больше камер.
OPERATOR_GAIN = 2

# КоАП РФ, ст. 5.27.1, ч. 1 и ч. 4, юрлица, ₽ (ред. от 04.08.2026), КонсультантПлюс.
FINE_PART1_RUB = (50_000, 80_000)
FINE_PART4_RUB = (130_000, 150_000)
# Адвокатская газета, 31.01.2022: компенсация морального вреда по делу о тяжёлой травме головы
# с инвалидностью III группы. Моральный вред возмещает работодатель, а не СФР.
MORAL_DAMAGE_EXAMPLE_RUB = 700_000


def cameras_per_board() -> int:
    return math.floor(ACCELERATOR_FPS / CAMERA_FPS)


def boards(cameras: int) -> int:
    return math.ceil(cameras / cameras_per_board())


def gross_salaries() -> list[float]:
    return [amount / NET_SHARE if is_net else amount for amount, is_net in OPERATOR_SALARIES_RUB]


def post_cost_per_month() -> float:
    """Месячная стоимость круглосуточного поста: медиана зарплаты до вычета × взносы × ставки."""
    staff_per_post = POST_HOURS_PER_YEAR / NORM_HOURS_2026
    return statistics.median(gross_salaries()) * (1 + INSURANCE_RATE) * staff_per_post


def capex(name: str, board_rub: float) -> dict:
    cameras = SCENARIOS[name]
    n_boards = boards(cameras)
    deploy_rub = (DEPLOY_HOURS_BASE + DEPLOY_HOURS_PER_CAMERA * cameras) * ENGINEER_RUB_PER_HOUR
    total = n_boards * board_rub + SERVER_RUB[name] + deploy_rub
    return {"cameras": cameras, "boards": n_boards, "boards_rub": n_boards * board_rub,
            "server_rub": SERVER_RUB[name], "deploy_rub": deploy_rub, "capex": total}


def posts_without_system(cameras: int, cameras_per_operator: int) -> int:
    return math.ceil(cameras / cameras_per_operator)


def conservative(name: str, board_rub: float) -> list[dict]:
    """Оператор остаётся и ведёт вдвое больше камер: экономия — половина стоимости постов."""
    total = capex(name, board_rub)["capex"]
    rows = []
    for per_operator in CAMERAS_PER_OPERATOR:
        posts = posts_without_system(SCENARIOS[name], per_operator)
        saving = posts * (1 - 1 / OPERATOR_GAIN) * post_cost_per_month()
        rows.append({"per_operator": per_operator, "posts": posts, "saving": saving,
                     "payback": total / saving})
    return rows


def optimistic(name: str, board_rub: float) -> dict:
    """Система заменяет все посты при наименьшей нагрузке на оператора."""
    posts = posts_without_system(SCENARIOS[name], CAMERAS_PER_OPERATOR[0])
    saving = posts * post_cost_per_month()
    return {"posts": posts, "saving": saving, "payback": capex(name, board_rub)["capex"] / saving}


def rub(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|---" * len(header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def capex_table() -> str:
    rows = {name: capex(name, BOARD_RUB) for name in SCENARIOS}
    fields = [("Плат LinQ", "boards", str), ("Платы, ₽", "boards_rub", rub),
              ("Сервер, ₽", "server_rub", rub), ("Внедрение, ₽", "deploy_rub", rub),
              ("Капитальные затраты, ₽", "capex", rub)]
    header = ["Показатель"] + [f"{n}, {r['cameras']} камер" for n, r in rows.items()]
    return table(header, [[title] + [fmt(r[key]) for r in rows.values()]
                          for title, key, fmt in fields])


def workshop_table() -> str:
    header = ["Сценарий, цех", "Камер на оператора без системы", "Постов без системы",
              "Экономия в месяц, ₽", "Окупаемость, мес."]
    rows = [["консервативный, оператор ведёт вдвое больше камер", str(r["per_operator"]),
             str(r["posts"]), rub(r["saving"]), f"{r['payback']:.1f}"]
            for r in conservative("цех", BOARD_RUB)]
    best = optimistic("цех", BOARD_RUB)
    rows.append(["оптимистичный, замена постов", str(CAMERAS_PER_OPERATOR[0]),
                 str(best["posts"]), rub(best["saving"]), f"{best['payback']:.1f}"])
    return table(header, rows)


def small_site_table() -> str:
    fines = (f"ч. 1: {rub(FINE_PART1_RUB[0])}–{rub(FINE_PART1_RUB[1])}; "
             f"ч. 4: {rub(FINE_PART4_RUB[0])}–{rub(FINE_PART4_RUB[1])}")
    system_rub = rub(capex("мастерская", BOARD_RUB)["capex"])
    rows = [["Стоимость системы, капитальные затраты", system_rub],
            ["Штраф по ст. 5.27.1 КоАП, юрлицо", fines],
            ["Стоимость одного несчастного случая для работодателя",
             "нет данных; ориентир: компенсация морального вреда "
             f"{rub(MORAL_DAMAGE_EXAMPLE_RUB)}"]]
    return table(["Мастерская, 5 камер", "₽"], rows)


def sensitivity_table() -> str:
    header = ["Цена платы LinQ, ₽", "Затраты, мастерская, ₽", "Затраты, цех, ₽",
              "Окупаемость, цех, консервативный, мес.", "Окупаемость, цех, оптимистичный, мес."]
    rows = []
    for price in BOARD_PRICES_RUB:
        paybacks = [r["payback"] for r in conservative("цех", price)]
        rows.append([rub(price), rub(capex("мастерская", price)["capex"]),
                     rub(capex("цех", price)["capex"]),
                     f"{min(paybacks):.1f}–{max(paybacks):.1f}",
                     f"{optimistic('цех', price)['payback']:.1f}"])
    return table(header, rows)


def main() -> None:
    print(f"Камер на плату при {CAMERA_FPS} кадрах/с: {cameras_per_board()}")
    print("Зарплаты до вычета, ₽: " + ", ".join(rub(s) for s in sorted(gross_salaries())))
    print(f"Медиана зарплаты оператора до вычета, ₽: {rub(statistics.median(gross_salaries()))}")
    print(f"Ставок на круглосуточный пост: {POST_HOURS_PER_YEAR / NORM_HOURS_2026:.2f}")
    print(f"Стоимость поста в месяц, ₽: {rub(post_cost_per_month())}")
    print(f"Цена платы LinQ (допущение), ₽: {rub(BOARD_RUB)}; аналоги: Hailo-8 "
          f"{rub(HAILO8_USD * USD_RUB)}, Jetson Orin NX 16GB {rub(ORIN_NX_USD * USD_RUB)}")
    for title, text in [("Капитальные затраты", capex_table()), ("Цех", workshop_table()),
                        ("Мастерская", small_site_table()),
                        ("Чувствительность", sensitivity_table())]:
        print(f"\n{title}\n{text}")


if __name__ == "__main__":
    main()
