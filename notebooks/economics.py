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
# Вилка → середина, «от» или «до» → указанная сумма; суммы на руки и до вычета налогов вместе.
OPERATOR_SALARIES_RUB = [135_000, 100_000, 90_000, 75_000, 109_607, 52_000, 109_607,
                         109_607, 105_000, 70_000]
# Страховые взносы работодателя, единый тариф: НК РФ, ст. 425.
INSURANCE_RATE = 0.30
# Часов в году на круглосуточном посту и норма часов на ставку при 40-часовой неделе в 2026 г.:
# производственный календарь 2026, buh.ru.
POST_HOURS_PER_YEAR = 24 * 365
NORM_HOURS_2026 = 1972
# Допущение: постов наблюдения, которые заменяет система (один оператор — 16–25 камер).
POSTS_REPLACED = {"мастерская": 1, "цех": 2}
# КоАП РФ, ст. 5.27.1, ч. 1 и ч. 4, юрлица, ₽ (ред. от 04.08.2026), КонсультантПлюс.
FINE_PART1_RUB = (50_000, 80_000)
FINE_PART4_RUB = (130_000, 150_000)

SENSITIVITY = (0.5, 1.0, 2.0)


def cameras_per_board() -> int:
    return math.floor(ACCELERATOR_FPS / CAMERA_FPS)


def boards(cameras: int) -> int:
    return math.ceil(cameras / cameras_per_board())


def post_cost_per_month() -> float:
    """Месячная стоимость круглосуточного поста: медиана зарплаты × взносы × ставки на пост."""
    staff_per_post = POST_HOURS_PER_YEAR / NORM_HOURS_2026
    salary = statistics.median(OPERATOR_SALARIES_RUB)
    return salary * (1 + INSURANCE_RATE) * staff_per_post


def scenario(name: str, board_rub: float) -> dict:
    cameras = SCENARIOS[name]
    n_boards = boards(cameras)
    deploy_rub = (DEPLOY_HOURS_BASE + DEPLOY_HOURS_PER_CAMERA * cameras) * ENGINEER_RUB_PER_HOUR
    capex = n_boards * board_rub + SERVER_RUB[name] + deploy_rub
    saving = POSTS_REPLACED[name] * post_cost_per_month()
    return {"cameras": cameras, "boards": n_boards, "boards_rub": n_boards * board_rub,
            "server_rub": SERVER_RUB[name], "deploy_rub": deploy_rub, "capex": capex,
            "posts": POSTS_REPLACED[name], "saving": saving, "payback": capex / saving}


def rub(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def main_table() -> str:
    rows = {name: scenario(name, BOARD_RUB) for name in SCENARIOS}
    lines = ["| Показатель | " + " | ".join(f"{n}, {r['cameras']} камер" for n, r in rows.items())
             + " |", "|---|" + "---|" * len(rows)]
    fields = [("Плат LinQ", lambda r: str(r["boards"])),
              ("Платы, ₽", lambda r: rub(r["boards_rub"])),
              ("Сервер, ₽", lambda r: rub(r["server_rub"])),
              ("Внедрение, ₽", lambda r: rub(r["deploy_rub"])),
              ("Капитальные затраты, ₽", lambda r: rub(r["capex"])),
              ("Заменяемых круглосуточных постов", lambda r: str(r["posts"])),
              ("Экономия в месяц, ₽", lambda r: rub(r["saving"])),
              ("Окупаемость, мес.", lambda r: f"{r['payback']:.1f}")]
    for title, value in fields:
        lines.append(f"| {title} | " + " | ".join(value(r) for r in rows.values()) + " |")
    fines = (f"ч. 1: {rub(FINE_PART1_RUB[0])}–{rub(FINE_PART1_RUB[1])}; "
             f"ч. 4: {rub(FINE_PART4_RUB[0])}–{rub(FINE_PART4_RUB[1])}")
    lines.append(f"| Предотвращённый штраф по ст. 5.27.1 КоАП, ₽, вне окупаемости | "
                 + " | ".join(fines for _ in rows) + " |")
    return "\n".join(lines)


def sensitivity_table() -> str:
    lines = ["| Цена платы LinQ, ₽ | " + " | ".join(f"Окупаемость, {n}, мес." for n in SCENARIOS)
             + " |", "|---|" + "---|" * len(SCENARIOS)]
    for factor in SENSITIVITY:
        price = BOARD_RUB * factor
        paybacks = [f"{scenario(n, price)['payback']:.1f}" for n in SCENARIOS]
        lines.append(f"| {rub(price)} ({factor * 100 - 100:+.0f} %) | " + " | ".join(paybacks)
                     + " |")
    return "\n".join(lines)


def main() -> None:
    print(f"Камер на плату при {CAMERA_FPS} кадрах/с: {cameras_per_board()}")
    print(f"Медиана зарплаты оператора, ₽: {rub(statistics.median(OPERATOR_SALARIES_RUB))}")
    print(f"Ставок на круглосуточный пост: {POST_HOURS_PER_YEAR / NORM_HOURS_2026:.2f}")
    print(f"Стоимость поста в месяц, ₽: {rub(post_cost_per_month())}")
    print(f"Цена платы LinQ (допущение), ₽: {rub(BOARD_RUB)}; аналоги: Hailo-8 "
          f"{rub(HAILO8_USD * USD_RUB)}, Jetson Orin NX 16GB {rub(ORIN_NX_USD * USD_RUB)}")
    print()
    print(main_table())
    print()
    print(sensitivity_table())


if __name__ == "__main__":
    main()
