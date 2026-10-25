import { useEffect, useMemo, type ReactNode } from 'react'
import { AlertFeed } from './alerts/AlertFeed.tsx'
import { AlertToasts } from './alerts/AlertToasts.tsx'
import { NotifyMenu } from './alerts/NotifyMenu.tsx'
import { useNotifySettings } from './alerts/notifySettings.ts'
import { AnalyticsPage } from './analytics/AnalyticsPage.tsx'
import { useAlertFeed } from './alerts/useAlertFeed.ts'
import { READ_ONLY_TITLE, useReadOnly } from './api/readOnly.ts'
import { dataSource, knownStatus } from './api/source.ts'
import { useServerStatus, type ServerStatus } from './api/useServerStatus.ts'
import { CamerasPage } from './cameras/CamerasPage.tsx'
import { IconBell, IconCamera, IconChart, IconGrid, IconHome, IconList, IconMoon, IconSun } from './components/Icons.tsx'
import { headerLogo } from './components/brandLogo.ts'
import { useTheme } from './components/useTheme.ts'
import { JournalPage } from './journal/JournalPage.tsx'
import { MonitorPage } from './monitor/MonitorPage.tsx'
import { OverviewPage } from './overview/OverviewPage.tsx'
import { routeHref, useRoute, type Page } from './router.ts'

// short: подпись в нижней панели телефона, где на раздел меньше 60 px
const NAV: { page: Page; title: string; short: string; icon: () => ReactNode }[] = [
  { page: 'overview', title: 'Обзор', short: 'Обзор', icon: IconHome },
  { page: 'monitor', title: 'Монитор', short: 'Монитор', icon: IconGrid },
  { page: 'alerts', title: 'Тревоги', short: 'Тревоги', icon: IconBell },
  { page: 'journal', title: 'Журнал', short: 'Журнал', icon: IconList },
  { page: 'cameras', title: 'Камеры и зоны', short: 'Камеры', icon: IconCamera },
  { page: 'analytics', title: 'Аналитика', short: 'Отчёты', icon: IconChart },
]

const BASE_TITLE = document.title

export default function App() {
  const server = useServerStatus()
  // Лента и её WebSocket живут на уровне приложения: тревоги приходят на любой странице
  const feed = useAlertFeed()
  const route = useRoute()
  const readOnly = useReadOnly()
  const { theme, toggle } = useTheme()
  const logo = headerLogo(theme)
  const [notify, setNotify] = useNotifySettings()

  const unhandled = useMemo(
    () => Object.values(feed.events).filter((e) => e.status === 'new').length + feed.hiddenNew,
    [feed.events, feed.hiddenNew],
  )

  useEffect(() => {
    document.title = unhandled ? `(${unhandled}) ${BASE_TITLE}` : BASE_TITLE
  }, [unhandled])

  // Новый раздел открывается с начала страницы
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [route.page])

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href={routeHref('overview')} aria-label="Сокол, охрана труда: на обзор">
            {/* Надпись «СОКОЛ» на логотипе — название сервиса, отдельным текстом не повторяется */}
            <img
              className="brand-logo"
              src={logo.src}
              alt="Сокол"
              style={{ aspectRatio: String(logo.ratio) }}
              draggable={false}
              data-logo={theme}
            />
            <span className="brand-sub">Охрана труда</span>
          </a>

          <nav className="nav" aria-label="Разделы">
            {NAV.map((item) => (
              <a
                key={item.page}
                href={routeHref(item.page)}
                aria-label={item.page === 'alerts' && unhandled > 0 ? `${item.title}, новых: ${unhandled}` : item.title}
                aria-current={route.page === item.page ? 'page' : undefined}
              >
                <item.icon />
                <span className="nav-label">{item.title}</span>
                <span className="nav-label-short" aria-hidden="true">
                  {item.short}
                </span>
                {item.page === 'alerts' && unhandled > 0 && (
                  <span className="nav-count" aria-label={`новых: ${unhandled}`}>
                    {unhandled > 99 ? '99+' : unhandled}
                  </span>
                )}
              </a>
            ))}
          </nav>

          <div className="topbar-end">
            <ServerPill server={server} />
            <NotifyMenu settings={notify} onChange={setNotify} />
            <button
              type="button"
              className="icon-btn"
              onClick={toggle}
              aria-label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
              title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
            >
              {theme === 'dark' ? <IconSun /> : <IconMoon />}
            </button>
          </div>
        </div>
      </header>

      <Banners server={server} readOnly={readOnly} />

      <main id="main" className="main">
        {route.page === 'overview' && <OverviewPage feed={feed} server={server} />}
        {route.page === 'monitor' && <MonitorPage params={route.params} server={server} feed={feed} />}
        {route.page === 'alerts' && <AlertFeed feed={feed} params={route.params} server={server} />}
        {route.page === 'journal' && <JournalPage params={route.params} subscribe={feed.subscribe} server={server} />}
        {route.page === 'cameras' && <CamerasPage params={route.params} server={server} />}
        {route.page === 'analytics' && <AnalyticsPage server={server} />}
      </main>

      <AlertToasts subscribe={feed.subscribe} events={feed.events} suppressed={route.page === 'alerts'} settings={notify} />
    </div>
  )
}

function ServerPill({ server }: { server: ServerStatus }) {
  if (server.state === 'loading') {
    return (
      <p className="pill muted" title="Подключение…">
        <span className="dot dot-wait" aria-hidden="true" /> <span className="pill-text">Подключение…</span>
      </p>
    )
  }
  if (server.state === 'offline') {
    return (
      <p className="pill pill-bad" title={server.error}>
        <span className="dot dot-off" aria-hidden="true" /> <span className="pill-text">Нет связи</span>
      </p>
    )
  }
  return (
    <p className="pill" title={`На связи. Детектор: ${server.status.detector} (${server.status.backend})`}>
      <span className="dot dot-on" aria-hidden="true" /> <span className="pill-text">На связи</span>
    </p>
  )
}

// Плашки под шапкой: нет связи, тестовые данные, режим просмотра
function Banners({ server, readOnly }: { server: ServerStatus; readOnly: string | null }) {
  const status = knownStatus(server)
  const source = status ? dataSource(status) : null
  if (server.state !== 'offline' && !source?.test && readOnly === null) return null

  return (
    <div className="banners">
      {server.state === 'offline' && (
        <p className="banner banner-bad" role="alert">
          <strong>Нет связи с сервером.</strong> Данные на экране могут быть устаревшими, подключение восстановится автоматически.
        </p>
      )}
      {source?.test && (
        <p className="banner banner-test" data-banner="test">
          <strong>Тестовые данные:</strong> тревоги созданы сервером, это не результат нейросети.
        </p>
      )}
      {readOnly !== null && (
        <p className="banner banner-info" data-banner="readonly">
          <strong>{READ_ONLY_TITLE}.</strong> Смотреть можно всё, менять статусы и зоны нельзя.
          {readOnly !== READ_ONLY_TITLE && <span className="muted"> Ответ сервера: «{readOnly}».</span>}
        </p>
      )}
    </div>
  )
}
