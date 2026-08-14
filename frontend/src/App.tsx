import { FormEvent, useEffect, useMemo, useState } from 'react'

type JobStatus = 'queued' | 'running' | 'completed' | 'failed'

type TTSJob = {
  id: string
  text: string
  reference_text: string
  speed: number
  nfe_steps: number
  status: JobStatus
  error?: string | null
  output_path?: string | null
  download_url?: string
}

type ReferenceFile = { name: string; size_bytes: number }
type Health = { status: string; device: string; model_loaded: boolean; queue_depth: number }

type SourceMode = 'upload' | 'workspace'

const qualityOptions = [
  { value: 16, title: 'รวดเร็ว', description: 'เหมาะกับการทดสอบข้อความ' },
  { value: 24, title: 'สมดุล', description: 'คุณภาพและเวลาประมวลผลพอดี' },
  { value: 32, title: 'คุณภาพสูง', description: 'แนะนำสำหรับงานจริง' },
  { value: 40, title: 'ละเอียดมาก', description: 'ใช้เวลาเพิ่มขึ้น' },
  { value: 48, title: 'สูงสุด', description: 'ช้าที่สุด เหมาะกับงานสำคัญ' },
]

const defaultReferenceText = 'กรอกข้อความที่ผู้พูดกล่าวไว้ในไฟล์เสียงต้นแบบ'

function fileSize(size: number): string {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function statusLabel(status: JobStatus): string {
  return {
    queued: 'รอคิวประมวลผล',
    running: 'กำลังสร้างเสียงด้วย GPU',
    completed: 'สร้างเสียงเสร็จแล้ว',
    failed: 'ไม่สามารถสร้างเสียงได้',
  }[status]
}

function App() {
  const [text, setText] = useState('')
  const [referenceText, setReferenceText] = useState('')
  const [speed, setSpeed] = useState(1)
  const [nfeSteps, setNfeSteps] = useState(32)
  const [sourceMode, setSourceMode] = useState<SourceMode>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [workspaceFiles, setWorkspaceFiles] = useState<ReferenceFile[]>([])
  const [workspaceReference, setWorkspaceReference] = useState('')
  const [job, setJob] = useState<TTSJob | null>(null)
  const [message, setMessage] = useState('')
  const [health, setHealth] = useState<Health | null>(null)
  const [loading, setLoading] = useState(false)

  const currentQuality = useMemo(
    () => qualityOptions.find((item) => item.value === nfeSteps) ?? qualityOptions[2],
    [nfeSteps],
  )

  async function refreshReferenceFiles() {
    try {
      const response = await fetch('/api/reference-files', { cache: 'no-store' })
      if (!response.ok) return
      const data = await response.json() as { files: ReferenceFile[] }
      setWorkspaceFiles(data.files)
    } catch {
      // The app remains usable with direct upload if the list cannot be read.
    }
  }

  async function refreshHealth() {
    try {
      const response = await fetch('/api/health', { cache: 'no-store' })
      if (!response.ok) return
      setHealth(await response.json() as Health)
    } catch {
      setHealth(null)
    }
  }

  useEffect(() => {
    void refreshReferenceFiles()
    void refreshHealth()
    const timer = window.setInterval(() => void refreshHealth(), 30000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`/api/jobs/${job.id}`, { cache: 'no-store' })
        if (!response.ok) throw new Error('ไม่สามารถตรวจสอบสถานะงานได้')
        const updated = await response.json() as TTSJob
        setJob(updated)
        if (updated.status === 'completed') setMessage('สร้างเสียงเสร็จแล้ว คุณสามารถฟังและดาวน์โหลดไฟล์ WAV ได้ทันที')
        if (updated.status === 'failed') setMessage(updated.error ?? 'ไม่สามารถสร้างเสียงได้')
      } catch (error) {
        setMessage(error instanceof Error ? error.message : 'เกิดข้อผิดพลาดในการตรวจสอบสถานะ')
      }
    }, 1500)
    return () => window.clearInterval(timer)
  }, [job?.id, job?.status])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setMessage('')
    setJob(null)

    if (!text.trim()) return setMessage('กรุณากรอกข้อความที่ต้องการสร้างเสียง')
    if (!referenceText.trim() || referenceText === defaultReferenceText) {
      return setMessage('กรุณากรอกข้อความที่พูดอยู่ในไฟล์เสียงต้นแบบให้ถูกต้อง')
    }
    if (sourceMode === 'upload' && !file) return setMessage('กรุณาอัปโหลดไฟล์เสียงต้นแบบ')
    if (sourceMode === 'workspace' && !workspaceReference) return setMessage('กรุณาเลือกไฟล์เสียงจาก workspace')

    setLoading(true)
    try {
      const formData = new FormData()
      formData.append('text', text.trim())
      formData.append('reference_text', referenceText.trim())
      formData.append('speed', String(speed))
      formData.append('nfe_steps', String(nfeSteps))
      if (sourceMode === 'upload' && file) formData.append('reference_file', file)
      if (sourceMode === 'workspace') formData.append('workspace_reference', workspaceReference)

      const response = await fetch('/api/jobs', { method: 'POST', body: formData })
      const data = await response.json() as TTSJob | { detail?: string }
      if (!response.ok) throw new Error('detail' in data ? data.detail : 'ไม่สามารถเริ่มงานสร้างเสียงได้')
      setJob(data as TTSJob)
      setMessage('รับงานแล้ว กำลังเตรียมโมเดลและประมวลผลเสียง…')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ')
    } finally {
      setLoading(false)
    }
  }

  function resetForm() {
    setText('')
    setReferenceText('')
    setFile(null)
    setWorkspaceReference('')
    setJob(null)
    setMessage('')
  }

  const working = loading || job?.status === 'queued' || job?.status === 'running'

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Thonburian TTS หน้าแรก">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span>
          <span>Thonburian <strong>TTS</strong></span>
        </a>
        <div className="status-chip" title="สถานะของบริการ">
          <span className={`status-dot ${health?.status === 'ok' ? 'online' : ''}`} />
          <span>{health ? `${health.device.toUpperCase()} พร้อมใช้งาน` : 'กำลังตรวจสอบบริการ'}</span>
        </div>
      </header>

      <section className="hero">
        <p className="eyebrow">THAI VOICE STUDIO</p>
        <h1>สร้างเสียงที่เป็นธรรมชาติ<br /><em>ในน้ำเสียงของคุณ</em></h1>
        <p className="hero-copy">เปลี่ยนข้อความภาษาไทยให้เป็นเสียงพูด พร้อมโคลนเอกลักษณ์ของผู้พูดจากตัวอย่างเสียงสั้น ๆ</p>
        <div className="hero-notes">
          <span>โคลนเสียงจากตัวอย่าง</span><span>ประมวลผลบน GPU</span><span>ดาวน์โหลด WAV ได้ทันที</span>
        </div>
      </section>

      <section className="workspace" aria-label="เครื่องมือสร้างเสียง">
        <form className="composer-card" onSubmit={handleSubmit}>
          <div className="card-heading">
            <span className="step-index">01</span>
            <div><h2>ข้อความสำหรับสร้างเสียง</h2><p>พิมพ์สิ่งที่คุณต้องการให้โมเดลพูด</p></div>
          </div>
          <label className="field-label" htmlFor="tts-text">ข้อความภาษาไทย</label>
          <textarea
            id="tts-text"
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="เช่น สวัสดีครับ ยินดีต้อนรับสู่ Thonburian TTS"
            maxLength={2500}
            rows={6}
          />
          <div className="field-meta"><span>แนะนำให้แบ่งข้อความยาวเป็นย่อหน้าสั้น ๆ</span><span>{text.length.toLocaleString('th-TH')} / 2,500</span></div>

          <div className="card-heading reference-heading">
            <span className="step-index">02</span>
            <div><h2>เสียงต้นแบบ</h2><p>ใช้เสียงพูดชัดเจนประมาณ 3–10 วินาทีเพื่อผลที่ดีที่สุด</p></div>
          </div>
          <div className="source-tabs" role="tablist" aria-label="แหล่งเสียงต้นแบบ">
            <button type="button" className={sourceMode === 'upload' ? 'active' : ''} onClick={() => setSourceMode('upload')}>อัปโหลดจากเครื่อง</button>
            <button type="button" className={sourceMode === 'workspace' ? 'active' : ''} onClick={() => setSourceMode('workspace')}>เลือกจาก Pod</button>
          </div>

          {sourceMode === 'upload' ? (
            <label className={`upload-zone ${file ? 'has-file' : ''}`}>
              <input type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/flac,audio/ogg,audio/aac,.wav,.mp3,.m4a,.flac,.ogg,.aac" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
              <span className="upload-icon">↑</span>
              {file ? <><strong>{file.name}</strong><small>{fileSize(file.size)} · คลิกเพื่อเปลี่ยนไฟล์</small></> : <><strong>วางหรือเลือกไฟล์เสียง</strong><small>รองรับ WAV, MP3, M4A, FLAC, OGG และ AAC · ไม่เกิน 80 MB</small></>}
            </label>
          ) : (
            <div className="workspace-picker">
              <div className="picker-title"><span>ไฟล์ใน <code>/workspace/reference-audio</code></span><button type="button" onClick={() => void refreshReferenceFiles()}>รีเฟรช</button></div>
              <select value={workspaceReference} onChange={(event) => setWorkspaceReference(event.target.value)}>
                <option value="">เลือกไฟล์เสียงต้นแบบ</option>
                {workspaceFiles.map((item) => <option key={item.name} value={item.name}>{item.name} ({fileSize(item.size_bytes)})</option>)}
              </select>
              {!workspaceFiles.length && <p className="picker-help">ยังไม่พบไฟล์ ให้คัดลอกไฟล์เสียงไว้ที่โฟลเดอร์ดังกล่าวผ่าน JupyterLab แล้วกดรีเฟรช</p>}
            </div>
          )}

          <label className="field-label" htmlFor="reference-text">ข้อความที่พูดในเสียงต้นแบบ</label>
          <textarea
            id="reference-text"
            value={referenceText}
            onChange={(event) => setReferenceText(event.target.value)}
            placeholder="พิมพ์ข้อความที่อยู่ในไฟล์เสียงต้นแบบให้ตรงที่สุด"
            maxLength={1000}
            rows={3}
          />

          <div className="settings-row">
            <div className="setting"><label htmlFor="speed">ความเร็วเสียง <output>{speed.toFixed(1)}×</output></label><input id="speed" type="range" min="0.7" max="1.3" step="0.1" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} /><div className="range-labels"><span>ช้า</span><span>เร็ว</span></div></div>
            <div className="setting"><label htmlFor="quality">คุณภาพ <output>{currentQuality.title}</output></label><select id="quality" value={nfeSteps} onChange={(event) => setNfeSteps(Number(event.target.value))}>{qualityOptions.map((item) => <option key={item.value} value={item.value}>{item.title} · {item.value} steps</option>)}</select><small>{currentQuality.description}</small></div>
          </div>

          <div className="action-row">
            <button className="primary-button" type="submit" disabled={working}>{working ? <><span className="spinner" />กำลังประมวลผล</> : <>สร้างเสียง <span>→</span></>}</button>
            <button className="secondary-button" type="button" onClick={resetForm} disabled={working}>เริ่มใหม่</button>
          </div>
        </form>

        <aside className="result-panel">
          <div className="result-header"><p className="eyebrow">OUTPUT</p><span className={job ? `job-status ${job.status}` : 'job-status idle'}>{job ? statusLabel(job.status) : 'รอสร้างเสียง'}</span></div>
          {!job && <div className="empty-output"><div className="wave-placeholder"><span /><span /><span /><span /><span /><span /><span /></div><h2>เสียงของคุณจะอยู่ที่นี่</h2><p>เติมข้อความและเสียงต้นแบบ แล้วเริ่มสร้างได้เลย</p></div>}
          {job && job.status !== 'completed' && <div className="processing-output"><div className="processing-wave"><span /><span /><span /><span /><span /></div><h2>{statusLabel(job.status)}</h2><p>{message || 'งานของคุณกำลังถูกจัดเตรียม'}</p></div>}
          {job?.status === 'failed' && <div className="error-box"><strong>ลองใหม่อีกครั้ง</strong><p>{job.error ?? message}</p></div>}
          {job?.status === 'completed' && job.download_url && <div className="completed-output"><div className="completed-badge">✓</div><h2>พร้อมฟังแล้ว</h2><p>{message}</p><audio controls src={job.download_url} /><a className="download-button" href={job.download_url} download="thonburian-tts.wav">ดาวน์โหลดไฟล์ WAV <span>↓</span></a></div>}
          {message && job?.status !== 'completed' && job?.status !== 'failed' && <p className="live-message" aria-live="polite">{message}</p>}
          <div className="privacy-note"><span>⌁</span><p>ไฟล์เสียงและผลลัพธ์จะถูกลบอัตโนมัติจากระบบหลังหมดเวลา</p></div>
        </aside>
      </section>

      <section className="tips-grid">
        <article><span>01</span><h3>เลือกเสียงที่สะอาด</h3><p>หลีกเลี่ยงเสียงดนตรีและเสียงรบกวน เพื่อให้โมเดลจับน้ำเสียงได้ชัดเจน</p></article>
        <article><span>02</span><h3>ระบุคำพูดให้ตรง</h3><p>ข้อความกำกับเสียงต้นแบบที่แม่นยำช่วยให้การโคลนเสียงเป็นธรรมชาติมากขึ้น</p></article>
        <article><span>03</span><h3>ใช้เสียงอย่างรับผิดชอบ</h3><p>อัปโหลดเฉพาะเสียงของคุณเอง หรือเสียงที่ได้รับอนุญาตจากเจ้าของเสียงแล้ว</p></article>
      </section>

      <footer><span>Thonburian TTS · RunPod GPU workspace</span><span>{health?.queue_depth ? `${health.queue_depth} งานในคิว` : 'พร้อมเริ่มงาน'}</span></footer>
    </main>
  )
}

export default App
