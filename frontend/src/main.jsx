import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const API = '/weather-dashboard/api/v1'
const BRAND_LOGO = 'https://cdn.macm.dev/macm-logo.webp'

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`)
  return body
}

function formatDate(value, options = {}) {
  return value ? new Date(value).toLocaleString(undefined, { timeZone: 'Asia/Colombo', ...options }) : '—'
}

function localDaylight(value) {
  const hour = Number(new Date(value).toLocaleString('en-US', { timeZone: 'Asia/Colombo', hour: 'numeric', hour12: false }))
  return hour >= 6 && hour < 18
}

function formatCountdown(value, now = Date.now()) {
  if (!value) return 'Learning schedule'
  const remaining = new Date(value).getTime() - now
  if (remaining <= 0) return 'Due now'
  const minutes = Math.floor(remaining / 60000)
  const hours = Math.floor(minutes / 60)
  return hours ? `In ${hours}h ${minutes % 60}m` : `In ${Math.max(minutes, 1)} min`
}

function formatInterval(seconds) {
  if (seconds < 90) return `every ${Math.max(Math.round(seconds), 1)} seconds`
  const minutes = Math.round(seconds / 60)
  if (minutes < 90) return `every ${minutes} minutes`
  const hours = Math.floor(minutes / 60)
  return `every ${hours}h ${minutes % 60}m`
}

function alertDelivery(item) {
  const labels = {
    accepted_by_telegram: 'Accepted by Telegram',
    suppressed_by_cooldown: 'Waiting for next eligible check',
    failed: 'Delivery failed',
    not_sent: 'Delivery unverified'
  }
  return labels[item.delivery_status] || 'Delivery unverified'
}

function Login({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  async function submit(event) {
    event.preventDefault()
    setError('')
    try {
      await api('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
      onLogin()
    } catch (err) { setError(err.message) }
  }
  return <main className="login-shell"><form className="login-card" onSubmit={submit}>
    <img className="brand-logo" src={BRAND_LOGO} alt="Development by MACM" />
    <div className="eyebrow">HORANA WEATHER MONITOR</div><h1>Welcome back</h1>
    <p className="muted">Private weather insights for your home network.</p>
    <label>Username<input value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" required /></label>
    <label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required /></label>
    {error && <div className="error">{error}</div>}<button className="primary">Sign in</button>
    <div className="brand-note">DEVELOPMENT BY MACM</div>
  </form></main>
}

function MetricCard({ label, value, unit, accent = false }) {
  return <div className={`metric${accent ? ' accent' : ''}`}><span>{label}</span><strong>{value ?? '—'}{value !== null && value !== undefined && unit ? ` ${unit}` : ''}</strong></div>
}

function NavIcon({ name }) {
  const paths = {
    home: <><path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9M9 20v-6h6v6"/></>,
    trends: <><path d="M3 17 9 11l4 4 8-9"/><path d="M15 6h6v6"/></>,
    activity: <><path d="M3 12h4l3-8 4 16 3-8h4"/></>,
    alerts: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
    power: <><path d="M12 3v9"/><path d="M7 5.8a8 8 0 1 0 10 0"/></>,
    access: <><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 1 1 8 0v3M12 14v3"/></>
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}

function WeatherIcon({ condition = 'clear', isDay = true, className = '' }) {
  const cloud = <><path d="M20 53h43c10 0 15-7 15-15 0-7-5-13-12-14-3-10-12-16-22-14-8 2-13 8-15 16-9-1-17 5-17 14 0 7 4 13 8 13Z" fill="#f8fcff" stroke="#7297b5" strokeWidth="3"/><path d="M22 47h43" stroke="#d9eaf5" strokeWidth="3" strokeLinecap="round"/></>
  const rain = <><path d="m26 61-5 11m21-11-5 11m21-11-5 11" stroke="#1688db" strokeWidth="4" strokeLinecap="round"/><path d="m34 75-2 5m21-5-2 5" stroke="#5be8ff" strokeWidth="3" strokeLinecap="round"/></>
  return <svg className={`weather-icon ${className}`} viewBox="0 0 96 96" fill="none" role="img" aria-label={`${condition} weather`}>
    {condition === 'clear' && (isDay ? <><circle cx="48" cy="46" r="18" fill="#ffce62" stroke="#f5a624" strokeWidth="3"/><circle cx="48" cy="46" r="25" stroke="#ffd889" strokeWidth="3" strokeDasharray="2 6"/><path d="M48 5v10M48 77v10M7 46h10m62 0h10M19 17l8 8m42 42 8 8m0-58-8 8M27 67l-8 8" stroke="#f5ae33" strokeWidth="4" strokeLinecap="round"/></> : <><path d="M62 16c-20 2-32 21-26 39 4 12 17 20 30 19-9 8-23 10-35 3-17-10-22-32-12-49C28 14 46 9 62 16Z" fill="#ffe9a8" stroke="#e9c57c" strokeWidth="3"/><circle cx="73" cy="23" r="2" fill="#87b4e5"/><circle cx="78" cy="51" r="2" fill="#87b4e5"/></>)}
    {condition === 'clouds' && <><circle cx="31" cy="28" r="13" fill={isDay ? '#ffce62' : '#ffe9a8'}/>{cloud}</>}
    {condition === 'fog' && <>{cloud}<path d="M10 63h66M20 73h65M8 83h53" stroke="#8baebd" strokeWidth="4" strokeLinecap="round" opacity=".8"/></>}
    {(condition === 'rain' || condition === 'thunder' || condition === 'snow') && <>{cloud}{condition === 'thunder' ? <path d="m52 55-13 19h11l-7 17 22-25H53l8-11Z" fill="#f9bc42" stroke="#db9429" strokeWidth="2"/> : condition === 'snow' ? <path d="M25 69h13m-6-6v13m24-7h13m-6-6v13" stroke="#5ba9d8" strokeWidth="3" strokeLinecap="round"/> : rain}</>}
    {!['clear', 'clouds', 'fog', 'rain', 'thunder', 'snow'].includes(condition) && <>{cloud}</>}
  </svg>
}

function WeatherHero({ weather, motionActive }) {
  if (!weather?.available) return <article className="weather-unavailable panel"><div className="eyebrow">HORANA WEATHER</div><h2>Sky report is warming up</h2><p>{weather?.message || 'Waiting for the monitor to send its first successful weather check.'}</p></article>
  const freshness = weather.freshness === 'fresh' ? 'Live from latest check' : `Last check ${Math.max(1, Math.round((weather.age_seconds || 0) / 60))} min ago · may be out of date`
  const day = weather.is_day ? 'day' : 'night'
  return <article className={`weather-hero ${weather.condition_key} ${day}${motionActive ? '' : ' paused'}`}>
    <div className="weather-art" aria-hidden="true"/><div className="weather-sky" aria-hidden="true"><i className="sky-light"/><i className="cloud cloud-one"/><i className="cloud cloud-two"/><i className="rain-streaks"/><i className="rain-streaks rain-near"/><i className="lightning"/><i className="sky-glow"/><i className="sky-stars"/><i className="sky-haze"/></div>
    <div className="hero-top"><div><div className="eyebrow">HORANA · SRI LANKA</div><h2>Weather right now</h2></div><span className={`weather-freshness ${weather.freshness}`}>{weather.freshness === 'fresh' ? '●' : '◷'} {freshness}</span></div>
    <div className="hero-main"><div><div className="hero-condition"><WeatherIcon condition={weather.condition_key} isDay={weather.is_day}/>{weather.condition}</div><div className="hero-temp">{weather.temperature_c == null ? '—' : Math.round(weather.temperature_c)}<sup>°</sup></div><div className="hero-feels">Feels like {weather.feels_like_c == null ? '—' : `${Math.round(weather.feels_like_c)}°`} <span>·</span> {weather.is_day ? 'Daytime' : 'Tonight'}</div></div>
      <div className="hero-metrics"><MetricCard label="Humidity" value={weather.humidity_percent == null ? null : Math.round(weather.humidity_percent)} unit="%"/><MetricCard label="Wind" value={weather.wind_speed == null ? null : Math.round(weather.wind_speed)} unit="m/s"/><MetricCard label="Rain chance" value={weather.precipitation_probability == null ? null : Math.round(weather.precipitation_probability)} unit="%" accent/><MetricCard label="Next hour" value={weather.forecast?.[0]?.precipitation_mm == null ? null : weather.forecast[0].precipitation_mm} unit="mm rain"/></div>
    </div>
    {!!weather.warnings?.length && <div className="official-weather-warning"><strong>Official weather warning</strong><span>{weather.warnings.slice(0, 2).join(' · ')}</span></div>}
    <div className="forecast-heading"><div><strong>Coming up</strong><span>Hourly forecast · next 12 hours</span></div><small>{weather.source === 'open_meteo' ? 'Open-Meteo' : 'OpenWeather'} · updated {formatDate(weather.observed_at, { timeStyle: 'short' })}</small></div>
    {weather.forecast?.length ? <div className="forecast-strip">{weather.forecast.map((hour, index) => <div className="forecast-hour" key={`${hour.time}-${index}`}><small>{formatDate(hour.time, { hour: 'numeric' })}</small><WeatherIcon className="forecast-icon" condition={hour.condition_key} isDay={localDaylight(hour.time)}/><strong>{hour.temperature_c == null ? '—' : `${Math.round(hour.temperature_c)}°`}</strong><small>{hour.precipitation_probability == null ? '—' : `${Math.round(hour.precipitation_probability)}%`}</small></div>)}</div> : <p className="forecast-empty">Hourly forecast will appear with the next monitor update.</p>}
  </article>
}

function Chart({ title, subtitle, history, field, color, unit = '', probability = false }) {
  const series = useMemo(() => {
    const groups = history.filter(row => row[field] != null).reduce((all, row) => {
      (all[row.provider] ||= []).push(row)
      return all
    }, {})
    return Object.entries(groups).map(([provider, rows]) => [provider, rows.slice().sort((a, b) => new Date(a.observed_at) - new Date(b.observed_at)).slice(-48)])
  }, [history, field])
  const allRows = series.flatMap(([, rows]) => rows)
  const values = allRows.map(row => Number(row[field]))
  const latestValue = allRows.reduce((latest, row) => !latest || new Date(row.observed_at) > new Date(latest.observed_at) ? row : latest, null)
  const times = allRows.map(row => new Date(row.observed_at).getTime())
  const maxValue = probability ? 100 : Math.max(...values, 1)
  const minValue = probability ? 0 : Math.min(...values, 0)
  const range = Math.max(maxValue - minValue, 1)
  const firstTime = times.length ? Math.min(...times) : 0
  const lastTime = times.length ? Math.max(...times) : firstTime + 1
  const palette = [color, 'var(--macm-azure)', 'var(--macm-sapphire)', 'var(--macm-mist)']
  return <article className="panel chart-panel">
    <div className="chart-heading"><div><div className="eyebrow">LAST {Math.min(allRows.length, 48)} READINGS</div><h2>{title}</h2><p className="muted">{subtitle}</p></div>{latestValue && <strong className="chart-current">{latestValue[field]}{unit}</strong>}</div>
    {allRows.length < 2 ? <div className="empty-chart">A few more readings will bring this chart to life.</div> : <><div className="chart-scroll"><svg className="line-chart" viewBox="0 0 700 190" role="img" aria-label={title}>
      {[36, 92, 148].map(y => <line key={y} x1="44" x2="676" y1={y} y2={y} className="grid-line" />)}
      <text x="4" y="40" className="axis-label">{Math.round(maxValue)}{unit}</text><text x="4" y="151" className="axis-label">{Math.round(minValue)}{unit}</text>
      {series.map(([provider, rows], seriesIndex) => {
        const colorValue = palette[seriesIndex % palette.length]
        const coords = rows.map(row => ({ row, x: 44 + ((new Date(row.observed_at).getTime() - firstTime) / Math.max(lastTime - firstTime, 1)) * 632, y: 148 - ((Number(row[field]) - minValue) / range) * 112 }))
        const path = coords.map(({ x, y }, index) => `${index ? 'L' : 'M'} ${x} ${y}`).join(' ')
        return <g key={provider}><path d={path} fill="none" stroke={colorValue} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />{coords.map(({ row, x, y }) => <circle key={`${provider}-${row.observed_at}`} cx={x} cy={y} r="3.2" fill={colorValue}><title>{provider}: {row[field]}{unit} · {formatDate(row.observed_at)}</title></circle>)}</g>
      })}
      <text x="44" y="178" className="axis-label">{formatDate(new Date(firstTime), { hour: 'numeric', minute: '2-digit' })}</text><text x="620" y="178" className="axis-label">{formatDate(new Date(lastTime), { hour: 'numeric', minute: '2-digit' })}</text>
    </svg></div><div className="chart-legend">{series.map(([provider], index) => <span key={provider}><i style={{ background: palette[index % palette.length] }} />{provider.replaceAll('_', ' ')}</span>)}</div></>}
  </article>
}

function EndpointCallCard({ call }) {
  const rawFeed = call.response_data?.raw_response
  const summary = call.summary || (call.status === 'success' ? 'Weather data received successfully.' : 'This request could not be completed.')
  return <details className="endpoint-card">
    <summary><span className={`call-status ${call.status === 'success' ? 'ok' : 'failed'}`} />
      <span className="endpoint-info"><strong>{call.endpoint}</strong><small>{call.category} · {formatDate(call.called_at, { dateStyle: 'medium', timeStyle: 'short' })}</small></span>
      <span className={`call-badge ${call.status === 'success' ? 'success' : 'failure'}`}>{call.status === 'success' ? 'Received' : 'Issue'}</span>
      {call.duration_ms != null && <span className="duration">{call.duration_ms} ms</span>}
    </summary>
    <div className="endpoint-detail"><p>{rawFeed ? 'Official warning feed response saved.' : summary}</p><details className="raw-response"><summary>View saved response details</summary><pre>{rawFeed || JSON.stringify(call.response_data, null, 2)}</pre></details></div>
  </details>
}

function Dashboard() {
  const [current, setCurrent] = useState([])
  const [weatherOverview, setWeatherOverview] = useState(null)
  const [status, setStatus] = useState(null)
  const [history, setHistory] = useState([])
  const [alerts, setAlerts] = useState([])
  const [calls, setCalls] = useState([])
  const [tokens, setTokens] = useState([])
  const [newToken, setNewToken] = useState(null)
  const [tab, setTab] = useState('overview')
  const [error, setError] = useState('')
  const [shutdownId, setShutdownId] = useState(null)
  const [shutdownStep, setShutdownStep] = useState(0)
  const [now, setNow] = useState(Date.now())
  const [streamState, setStreamState] = useState('connecting')
  const [lastUpdated, setLastUpdated] = useState(null)
  const [motionActive, setMotionActive] = useState(!document.hidden)
  const loadSequence = useRef(0)

  async function load() {
    const sequence = ++loadSequence.current
    const requests = [
      ['/weather/current', setCurrent], ['/weather/overview', setWeatherOverview],
      ['/status', setStatus], ['/weather/history?limit=120', setHistory],
      ['/alerts?limit=20', setAlerts], ['/monitoring/endpoint-calls?limit=100', setCalls]
    ]
    const results = await Promise.allSettled(requests.map(([path]) => api(path)))
    if (sequence !== loadSequence.current) return
    const failures = []
    let successes = 0
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') { requests[index][1](result.value); successes++ }
      else failures.push(requests[index][0])
    })
    if (successes) setLastUpdated(Date.now())
    setError(failures.length ? `Some sections could not update (${failures.join(', ')}). The rest are current.` : '')
  }
  async function loadTokens() { try { setTokens(await api('/tokens')) } catch (err) { setError(err.message) } }
  useEffect(() => {
    load(); loadTokens()
    const events = new EventSource(`${API}/monitoring/events`, { withCredentials: true })
    events.onopen = () => setStreamState('connected')
    events.addEventListener('monitoring', () => load())
    events.onerror = () => setStreamState('reconnecting')
    const timer = setInterval(load, 30000)
    const clock = setInterval(() => setNow(Date.now()), 15000)
    const visibility = () => { setMotionActive(!document.hidden); if (!document.hidden) load() }
    document.addEventListener('visibilitychange', visibility)
    return () => { events.close(); clearInterval(timer); clearInterval(clock); document.removeEventListener('visibilitychange', visibility) }
  }, [])

  const groupedCalls = useMemo(() => calls.reduce((groups, item) => { (groups[item.category] ||= []).push(item); return groups }, {}), [calls])
  async function createToken(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    try { setNewToken(await api('/tokens', { method: 'POST', body: JSON.stringify({ name: form.get('name'), scopes: ['weather:read', 'alerts:read', 'status:read'] }) })); event.currentTarget.reset(); loadTokens() }
    catch (err) { setError(err.message) }
  }
  async function revoke(id) { try { await api(`/tokens/${id}/revoke`, { method: 'POST' }); loadTokens() } catch (err) { setError(err.message) } }
  async function requestShutdown() {
    if (shutdownStep === 0) { setShutdownStep(1); return }
    try { const result = await api('/shutdown/requests', { method: 'POST' }); setShutdownId(result.id); setShutdownStep(0) }
    catch (err) { setError(err.message) }
  }
  async function cancelShutdown() { if (!shutdownId) return; try { await api(`/shutdown/requests/${shutdownId}/cancel`, { method: 'POST' }); setShutdownId(null) } catch (err) { setError(err.message) } }

  const nav = [
    ['overview', 'Today', 'home'], ['history', 'Trends', 'trends'], ['calls', 'Activity', 'activity'],
    ['alerts', 'Alerts', 'alerts'], ['shutdown', 'Power', 'power'], ['tokens', 'Access', 'access']
  ]
  const page = nav.find(([key]) => key === tab)
  const nextRun = status?.next_run_estimate
  const dataIsStale = !weatherOverview?.available || !weatherOverview?.observed_at || now - new Date(weatherOverview.observed_at).getTime() > 20 * 60 * 1000
  return <main className="app-frame">
    <aside className="sidebar">
      <div className="sidebar-brand"><img className="brand-logo" src={BRAND_LOGO} alt="Development by MACM"/><span className="workspace-chip"><i/> HOME WEATHER</span></div>
      <div className="nav-caption">YOUR WEATHER</div>
      <nav className="side-nav" aria-label="Main navigation">{nav.slice(0, 4).map(([key, label, icon]) => <button key={key} className={tab === key ? 'selected' : ''} onClick={() => setTab(key)}><span className="nav-icon"><NavIcon name={icon}/></span><span>{label}</span>{key === 'alerts' && alerts.length > 0 && <small>{alerts.length}</small>}</button>)}</nav>
      <div className="nav-caption tools-caption">TOOLS</div>
      <nav className="side-nav" aria-label="Tools">{nav.slice(4).map(([key, label, icon]) => <button key={key} className={tab === key ? 'selected' : ''} onClick={() => setTab(key)}><span className="nav-icon"><NavIcon name={icon}/></span><span>{label}</span></button>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-status"><span className={`status-pulse ${weatherOverview?.freshness === 'fresh' ? 'online' : ''}`}/><div><strong>Weather data</strong><small>{weatherOverview?.freshness === 'fresh' ? `Checked ${formatDate(weatherOverview.observed_at, { hour: 'numeric', minute: '2-digit' })}` : weatherOverview?.freshness === 'stale' ? 'Latest reading may be old' : 'Waiting for first check'}</small></div></div><button className="profile-button" onClick={async () => { await api('/auth/logout', { method: 'POST' }); location.reload() }}><span className="profile-avatar">M</span><span><strong>MACM</strong><small>Administrator</small></span><b>↗</b></button></div>
    </aside>
    <div className="app-body">
      <header className="appbar"><div className="app-title"><div className="eyebrow">HORANA, SRI LANKA <span>·</span> PRIVATE WEATHER</div><h1>{page?.[1] || 'Weather'}</h1><p>{tab === 'overview' ? 'A clear view of the sky and what’s coming next.' : tab === 'history' ? 'See how conditions have changed over time.' : tab === 'calls' ? 'A simple timeline of the latest weather checks.' : tab === 'alerts' ? 'Weather notices and delivery history.' : tab === 'shutdown' ? 'Manage the home server power request.' : 'Manage devices that can read your weather data.'}</p></div><div className="appbar-actions"><div className={`live-indicator ${dataIsStale ? 'stale' : streamState}`} role="status"><i/><strong>{dataIsStale ? 'Weather data is stale' : streamState === 'connected' ? 'Live updates on' : 'Reconnecting'}</strong><small>{lastUpdated ? `Page updated ${formatDate(lastUpdated, { timeStyle: 'short' })}` : 'Waiting for update'}</small></div><span className="top-clock">{formatDate(now, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span><button className="refresh-button" onClick={load} aria-label="Refresh dashboard" title="Refresh dashboard">⟳ <span>Refresh</span></button></div></header>
      {error && <div className="error banner">{error}</div>}
      <div className="page-content" key={tab}>
        {tab === 'overview' && <section className="page-enter">
          <div className="summary-row">
            <article className="summary-card next-check"><span className="summary-icon">◷</span><div><small>NEXT WEATHER CHECK</small><strong>{formatCountdown(nextRun, now)}</strong><span>{nextRun ? formatDate(nextRun, { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : 'Estimate appears after more readings'}</span></div><div className="schedule-track"><i/></div></article>
            <article className="summary-card"><span className="summary-icon blue">↗</span><div><small>CHECK FREQUENCY</small><strong>{status?.estimated_interval_seconds ? formatInterval(status.estimated_interval_seconds) : 'Learning schedule'}</strong><span>{status?.latest_run ? `Last checked ${formatDate(status.latest_run, { timeStyle: 'short' })}` : 'No checks recorded yet'}</span></div></article>
            <article className="summary-card"><span className="summary-icon aqua">⌁</span><div><small>WEATHER HISTORY</small><strong>{history.length ? `${history.length} recent readings` : 'Ready for first reading'}</strong><span>Weather updates are kept for 90 days</span></div></article>
          </div>
          <WeatherHero weather={weatherOverview} motionActive={motionActive}/>
          <div className="content-heading"><div><div className="eyebrow">AT A GLANCE</div><h2>Today’s conditions</h2><p>Weather readings from the connected forecast services.</p></div><button className="subtle-button" onClick={() => setTab('history')}>Explore trends <span>→</span></button></div>
          {current.length ? <div className="provider-grid">{current.map(item => <article className="provider-card" key={item.provider}><div className="provider-top"><div><div className="eyebrow">FORECAST SOURCE</div><div className="provider-name">{item.provider.replaceAll('_', ' ')}</div></div><span className={`provider-state ${item.error ? 'offline' : ''}`}>{item.error ? 'Needs attention' : 'Connected'}</span></div><div className="provider-temp">{item.temperature_c ?? '—'}<sup>°C</sup></div><div className="provider-data"><MetricCard label="Rain expected" value={item.precipitation_mm} unit="mm"/><MetricCard label="Chance of rain" value={item.precipitation_probability} unit="%" accent/><MetricCard label="Wind speed" value={item.wind_speed} unit="m/s"/><MetricCard label="Storm signal" value={item.thunder ? 'Elevated' : 'Low'}/></div><div className="provider-foot"><span className="provider-dot"/> Checked {formatDate(item.observed_at, { hour: 'numeric', minute: '2-digit' })}{item.error ? ` · ${item.error}` : ''}</div></article>)}</div> : <div className="empty-state warm-empty"><span className="empty-orbit">☼</span><strong>Your weather feed is ready</strong><span>The first successful monitor check will fill in conditions, forecasts, and trends here.</span></div>}
          <div className="overview-bottom"><article className="panel recent-panel"><div className="panel-heading"><div><div className="eyebrow">RECENT ACTIVITY</div><h2>Latest weather checks</h2></div><button className="subtle-button" onClick={() => setTab('calls')}>See activity <span>→</span></button></div>{calls.slice(0, 3).length ? calls.slice(0, 3).map(item => <EndpointCallCard key={item.id} call={item}/>) : <div className="inline-empty">Checks will show here with a plain-language status and the time received.</div>}</article>
            <article className="panel insight-card"><div className="eyebrow">YOUR HOME FORECAST</div><h2>{weatherOverview?.available ? `${weatherOverview.condition} in Horana` : 'Local weather, made simple'}</h2><p>{weatherOverview?.available ? `Current conditions from ${weatherOverview.source === 'open_meteo' ? 'Open-Meteo' : 'OpenWeather'}. The forecast refreshes after each monitor check.` : 'Your dashboard is ready to turn each monitor check into an easy-to-read local forecast.'}</p><div className="insight-meta"><span className="insight-spark">✳</span><span>Horana, Western Province</span></div></article></div>
        </section>}
        {tab === 'history' && <section className="page-enter"><div className="summary-row compact-summary"><article className="summary-card"><span className="summary-icon">⌁</span><div><small>READINGS SHOWN</small><strong>{history.length}</strong><span>Most recent measurements</span></div></article><article className="summary-card"><span className="summary-icon blue">◷</span><div><small>RETENTION</small><strong>90 days</strong><span>Automatic data history</span></div></article></div><div className="chart-grid"><Chart title="Chance of rain" subtitle="How forecast rain probability has moved over recent checks" history={history} field="precipitation_probability" color="var(--macm-blue)" unit="%" probability/><Chart title="Temperature" subtitle="Temperature readings from each forecast service" history={history} field="temperature_c" color="var(--macm-sapphire)" unit="°"/></div><section className="panel history-panel"><div className="panel-heading"><div><div className="eyebrow">RECENT MEASUREMENTS</div><h2>Weather history</h2><p>Each row is one saved provider reading.</p></div><button className="refresh-button" onClick={load}>⟳ <span>Refresh</span></button></div>{history.length ? <div className="history-list">{history.map(item => <article className="history-row" key={`${item.provider}-${item.observed_at}`}><span className="history-weather">{item.thunder ? 'ϟ' : item.precipitation_probability >= 60 ? '☂' : '☼'}</span><span className="history-when"><strong>{formatDate(item.observed_at, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</strong><small>{item.provider.replaceAll('_', ' ')}</small></span><span className="history-reading"><small>Temperature</small><strong>{item.temperature_c ?? '—'}°</strong></span><span className="history-reading"><small>Rain chance</small><strong>{item.precipitation_probability ?? '—'}%</strong></span><span className="history-reading"><small>Wind</small><strong>{item.wind_speed ?? '—'} m/s</strong></span><span className={`history-condition ${item.thunder ? 'storm' : ''}`}>{item.thunder ? 'Storm risk' : item.precipitation_probability >= 60 ? 'Rain possible' : 'Typical'}</span></article>)}</div> : <div className="empty-state"><strong>No readings to chart yet</strong><span>When the monitor sends its next successful weather check, measurements will appear here.</span></div>}</section></section>}
        {tab === 'calls' && <section className="page-enter"><div className="summary-row compact-summary"><article className="summary-card"><span className="summary-icon blue">↗</span><div><small>WEATHER CHECKS</small><strong>{calls.length}</strong><span>Saved endpoint responses</span></div></article><article className="summary-card"><span className="summary-icon aqua">✓</span><div><small>SUCCESSFUL</small><strong>{calls.filter(call => call.status === 'success').length}</strong><span>Most recent calls first</span></div></article></div><section className="panel calls-panel"><div className="panel-heading"><div><div className="eyebrow">ACTIVITY FEED</div><h2>Weather checks</h2><p>Choose a check to view the detailed response saved from that service.</p></div><button className="refresh-button" onClick={load}>⟳ <span>Refresh</span></button></div>{Object.keys(groupedCalls).length ? Object.entries(groupedCalls).map(([category, items]) => <div className="call-group" key={category}><div className="call-group-heading"><h3>{category}</h3><span>{items.length} {items.length === 1 ? 'check' : 'checks'}</span></div>{items.map(item => <EndpointCallCard key={item.id} call={item}/>)}</div>) : <div className="empty-state"><strong>No weather checks recorded yet</strong><span>Once the monitor completes a check, you’ll see the time, result, and saved response here.</span></div>}</section></section>}
        {tab === 'alerts' && <section className="panel page-enter"><div className="panel-heading"><div><div className="eyebrow">WEATHER NOTICES</div><h2>Alerts & warnings</h2><p>Official warnings and alert delivery history. Older records marked “Delivery unverified” cannot confirm whether Telegram received them.</p></div><span className="count-pill">{alerts.length} {alerts.length === 1 ? 'notice' : 'notices'}</span></div>{alerts.length === 0 ? <div className="empty-state"><span className="empty-orbit">✳</span><strong>All quiet for now</strong><span>Weather alerts will appear here if the monitor detects severe conditions.</span></div> : <div className="feed">{alerts.map(item => <div className="feed-row alert-row" key={item.id}><div><strong>{item.reason}</strong><p>{item.detail || 'No additional detail'}</p>{item.delivery_detail && <small>{item.delivery_detail}</small>}{item.next_eligible_at && <small>Next eligible check after {formatDate(item.next_eligible_at)}</small>}</div><div className="delivery-meta"><span className={`delivery-badge ${item.delivery_status || 'not_sent'}`}>{alertDelivery(item)}</span><time>{formatDate(item.sent_at)}</time></div></div>)}</div>}</section>}
        {tab === 'shutdown' && <section className="panel danger-panel page-enter"><div className="eyebrow">HOME SERVER</div><h2>Power controls</h2><p>Request a graceful shutdown of the home server. You can cancel during the 30-second safety window.</p>{shutdownId ? <div className="shutdown-result"><strong>Shutdown request created</strong><p>Request ID: {shutdownId}</p><button className="danger" onClick={cancelShutdown}>Cancel request</button></div> : <button className="danger" onClick={requestShutdown}>{shutdownStep === 0 ? 'Review shutdown request' : 'Confirm shutdown request'}</button>}{shutdownStep === 1 && <p className="warning">Confirm once more to create the request.</p>}</section>}
        {tab === 'tokens' && <section className="grid-two page-enter"><div className="panel"><div className="eyebrow">CONNECTED DEVICES</div><h2>Add a device</h2><p className="muted">Create a read-only key for a trusted device or home automation. The key is shown once.</p><form onSubmit={createToken}><label>Device name<input name="name" placeholder="Home automation" required/></label><button className="primary">Create device key</button></form>{newToken && <div className="token-box"><strong>Copy this key now</strong><code>{newToken.token}</code></div>}</div><div className="panel"><div className="eyebrow">DEVICE ACCESS</div><h2>Connected keys</h2>{tokens.length ? tokens.map(token => <div className="token-row" key={token.id}><div><strong>{token.name}</strong><small>{token.prefix} · {token.scopes.join(', ')}</small></div>{token.revoked_at ? <span className="muted">Revoked</span> : <button className="ghost" onClick={() => revoke(token.id)}>Revoke</button>}</div>) : <p className="muted">No device keys created.</p>}</div></section>}
      </div>
      <footer className="app-footer"><img src={BRAND_LOGO} alt=""/><span>Development by MACM</span><i/> <span>Made for weather at home</span></footer>
    </div>
    <nav className="mobile-dock" aria-label="Main navigation">{nav.map(([key, label, icon]) => <button key={key} className={tab === key ? 'selected' : ''} onClick={() => setTab(key)}><span className="dock-icon"><NavIcon name={icon}/></span><small>{label}</small></button>)}</nav>
  </main>
}

function App() {
  const [loggedIn, setLoggedIn] = useState(null)
  useEffect(() => { api('/auth/me').then(() => setLoggedIn(true)).catch(() => setLoggedIn(false)) }, [])
  if (loggedIn === null) return <main className="login-shell"><p>Loading…</p></main>
  return loggedIn ? <Dashboard /> : <Login onLogin={() => setLoggedIn(true)} />
}

createRoot(document.getElementById('root')).render(<App />)
