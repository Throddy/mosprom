// Понятные подписи параметров правил. Список параметров и единицы берутся из GET /api/rules,
// здесь только названия для частых параметров; остальные показываются по имени из API
const LABELS: Record<string, string> = {
  min_duration: 'Время до тревоги',
  dist: 'Опасное расстояние',
  speed: 'Скорость бега',
}

// Параметры, которые видны сразу; остальные — в «Тонкой настройке»
export const BASIC_PARAMS = new Set(Object.keys(LABELS))

export function paramLabel(name: string): string {
  return LABELS[name] ?? name
}
