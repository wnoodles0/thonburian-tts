# Thonburian TTS for RunPod

โครงการนี้ปรับปรุง [ThonburianTTS](https://github.com/biodatlab/thonburian-tts) ให้เป็น Docker template ส่วนตัวสำหรับ **RunPod Pod แบบเปิดค้าง** โดยมีเว็บ UI ใหม่สำหรับสร้างเสียงภาษาไทยและโคลนเสียงจากตัวอย่างเสียง ผู้ใช้สามารถอัปโหลดเสียงจากเครื่อง หรือเลือกไฟล์ที่เก็บใน Pod ได้โดยตรง

> **สรุปคำตอบเรื่องพอร์ต:** Pod เดียวสามารถให้บริการทั้ง **JupyterLab ที่พอร์ต 8888** และ **Thonburian TTS UI ที่พอร์ต 7777** พร้อมกันได้ เพียงกำหนดทั้งสองเป็น HTTP ports ใน Pod template [1] [2]

| รายการ | การตั้งค่า |
|---|---|
| รูปแบบ deployment | Private Docker template สำหรับ RunPod Pod |
| เว็บแอปหลัก | `7777` ผ่าน FastAPI และ React UI |
| JupyterLab | `8888` โดยคง token protection จาก RunPod base image |
| โมเดล | ThonburianTTS MegaF5 Thai checkpoint จาก Hugging Face |
| การใช้ GPU | โหลดโมเดลครั้งเดียวเมื่อมีงานแรก และรันงานทีละงานเพื่อไม่ให้ VRAM ชนกัน |
| ที่เก็บไฟล์ชั่วคราว | `/workspace` ซึ่งควรผูกกับ volume ของ Pod |
| การเก็บประวัติ | ไม่มี; ไฟล์อัปโหลดและเสียงผลลัพธ์ถูกลบตามเวลาที่ตั้งไว้ |

## สิ่งที่เพิ่มจากโครงการต้นทาง

หน้าเว็บใหม่มีฟอร์มภาษาไทยที่รวมขั้นตอนสำคัญไว้ในหน้าเดียว ได้แก่ การป้อนข้อความ, การอัปโหลดหรือเลือกไฟล์เสียงต้นแบบจาก `/workspace/reference-audio`, การกรอก transcription ของเสียงต้นแบบ, การกำหนดความเร็ว และการเลือกคุณภาพของการสร้างเสียง ระบบสร้างงานแบบเบื้องหลังและให้หน้าเว็บตรวจสถานะแยกต่างหาก จึงไม่หลุดเมื่อการประมวลผลใช้เวลานาน

ระบบจะโหลดโมเดลลง GPU เพียงครั้งเดียวเมื่อเริ่มงานแรก พร้อมจัดคิว inference ครั้งละหนึ่งงาน เพื่อรักษาเสถียรภาพของ VRAM สำหรับการใช้งานคนเดียวหรือทีมขนาดเล็ก นอกจากนี้ยังปรับ import ที่ขาดในสำเนา source ต้นทางเพื่อหลีกเลี่ยงข้อผิดพลาดระหว่าง inference

## 1. Build และ Push Docker Image

คุณต้องมีบัญชี Docker Hub หรือ registry ที่รองรับ OCI image ก่อนดำเนินการ คำสั่งด้านล่างใช้ Docker Hub เป็นตัวอย่าง โดยแทน `<dockerhub-user>` ด้วยชื่อบัญชีของคุณ

```bash
cd app

docker login
docker build -t <dockerhub-user>/thonburian-tts:1.0.0 .
docker push <dockerhub-user>/thonburian-tts:1.0.0
```

Dockerfile ใช้ `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` ซึ่งเป็น image ที่ RunPod ใช้ในคู่มือสร้าง custom Pod template [1] และ build React UI แยกเป็นขั้นก่อนคัดลอกเฉพาะ static files เข้าสู่ image สุดท้าย

> หากใช้ GitHub Container Registry ให้แทน image tag ตัวอย่างด้วย `ghcr.io/<github-user>/thonburian-tts:1.0.0` และตั้ง visibility ให้ RunPod pull ได้

## 2. สร้าง Private Pod Template

ไปที่ **RunPod Console → Templates → New Template** แล้วระบุ Docker image ที่ push ในขั้นตอนก่อนหน้า ให้ใช้ template แบบ **Private** และกำหนดพอร์ต HTTP ตามตารางนี้ RunPod รองรับการกำหนด HTTP ports ใน custom template เพื่อเปิด web UI/API ผ่าน proxy [1] [2]

| ช่องใน Template | ค่าแนะนำ |
|---|---|
| Template name | `Thonburian TTS` |
| Container image | `<dockerhub-user>/thonburian-tts:1.0.0` |
| Container disk | อย่างน้อย 20 GB |
| Volume disk | แนะนำ 30 GB ขึ้นไป เพื่อเก็บ cache โมเดลและไฟล์ workspace |
| HTTP Ports | `7777,8888` |
| TCP Ports | เว้นว่าง หากไม่ต้องการ SSH แบบ TCP โดยตรง |
| Environment variables | ไม่ต้องระบุสำหรับการใช้งานพื้นฐาน |

หลังสร้าง template ให้สร้าง **Pod** จาก template นี้และเลือก GPU ตามที่ทีมมีสิทธิ์ใช้งาน โดยควรเลือก GPU ที่มี CUDA และ VRAM เพียงพอกับโมเดลและงานเสียงของคุณ ครั้งแรกที่มีการสร้างเสียง ระบบจะดาวน์โหลด checkpoint ไปที่ `/workspace/models/huggingface` จึงควรรอให้การดาวน์โหลดเสร็จก่อนประเมินเวลา inference

## 3. เข้าใช้งานหลัง Pod พร้อม

เมื่อสถานะ Pod เป็น Running ให้เปิดเมนู **Connect** ของ Pod จะปรากฏ HTTP services ที่ตั้งไว้ [3]

| บริการ | พอร์ต | วิธีใช้ |
|---|---:|---|
| Thonburian TTS UI | `7777` | เปิดลิงก์ HTTP service ของพอร์ต 7777 เพื่อใช้งานหน้าเว็บสร้างเสียง |
| JupyterLab | `8888` | เปิดลิงก์ HTTP service ของพอร์ต 8888 และใช้ token ที่ RunPod/JupyterLab แสดง |

JupyterLab ยังคงเป็นบริการที่มี token protection; เว็บ TTS ที่พอร์ต 7777 ไม่มีหน้า login ตามความต้องการสำหรับใช้งานส่วนตัว อย่างไรก็ดี ควรเก็บ URL ของ Pod ไว้เฉพาะทีมที่ได้รับอนุญาต

## 4. ใช้งานโคลนเสียงผ่านหน้าเว็บ

เริ่มด้วยข้อความที่ต้องการให้โมเดลพูด จากนั้นเลือกแหล่งของ **เสียงต้นแบบ** ได้สองวิธี

| วิธี | ขั้นตอน |
|---|---|
| อัปโหลดจากเครื่อง | เลือกแท็บ `อัปโหลดจากเครื่อง` แล้วเลือก WAV, MP3, M4A, FLAC, OGG หรือ AAC ขนาดไม่เกิน 80 MB |
| ใช้ไฟล์ใน Pod | อัปโหลดไฟล์ผ่าน JupyterLab ไปที่ `/workspace/reference-audio` เลือกแท็บ `เลือกจาก Pod` กด `รีเฟรช` แล้วเลือกชื่อไฟล์ |

กรอกคำพูดที่อยู่ในไฟล์เสียงต้นแบบให้ตรงที่สุด เลือกความเร็วและคุณภาพ แล้วกด **สร้างเสียง** หน้าเว็บจะแสดงสถานะของงาน เมื่อเสร็จแล้วสามารถฟังและดาวน์โหลดไฟล์ WAV ได้ทันที

> เพื่อคุณภาพที่ดี ให้ใช้เสียงต้นแบบที่เป็นเสียงพูดชัดเจนราว 3–10 วินาที มีเสียงรบกวนน้อย และมีข้อความกำกับตรงกับที่พูดจริง ตามคำแนะนำของโครงการต้นทาง [4]

## 5. ตรวจสอบสถานะและแก้ปัญหา

เปิด Terminal ใน JupyterLab แล้วใช้คำสั่งต่อไปนี้ หากจำเป็นต้องตรวจว่าบริการและ GPU ทำงานอยู่หรือไม่

```bash
# ตรวจบริการ TTS ภายใน Pod
curl http://127.0.0.1:7777/api/health

# ดู log ของ container process
ps aux | grep -E 'uvicorn|jupyter' | grep -v grep

# ตรวจ GPU และ VRAM
nvidia-smi

# ดูไฟล์ output ที่ยังไม่หมดอายุ
ls -lah /workspace/outputs
```

| อาการ | สาเหตุที่เป็นไปได้ | แนวทางแก้ไข |
|---|---|---|
| UI เปิดไม่ได้ | ลืมเพิ่ม `7777` ใน HTTP Ports หรือ Pod ยัง start ไม่เสร็จ | ตรวจ template และรอให้ container boot จบ จากนั้นเปิดลิงก์พอร์ต 7777 ในหน้า Connect |
| JupyterLab เข้าไม่ได้ | ใช้ URL ของ UI แทน หรือไม่มี token | เปิด HTTP service พอร์ต 8888 และใช้ Jupyter token ตามปกติ |
| งานค้างที่กำลังเตรียมโมเดล | กำลังดาวน์โหลด checkpoint ครั้งแรก | รอสักครู่ และตรวจ log/container หรือพื้นที่ใน `/workspace` |
| งานสร้างเสียงไม่สำเร็จ | ไฟล์ต้นแบบไม่ใช่ไฟล์เสียงที่รองรับ ข้อความกำกับว่าง หรือ GPU/VRAM ไม่พร้อม | ใช้ไฟล์เสียงที่ชัดเจน กรอก transcription และตรวจ `nvidia-smi` |
| ไม่พบไฟล์ในแท็บ Pod | ไฟล์ไม่ได้อยู่ในโฟลเดอร์ที่ UI อ่าน | ย้ายไฟล์ไปที่ `/workspace/reference-audio` แล้วกดรีเฟรช |

## 6. Environment Variables ที่ปรับได้

ไม่ต้องตั้งค่าใด ๆ สำหรับการใช้งานมาตรฐาน หากต้องการปรับ deployment ให้ใส่ค่าเหล่านี้ใน Pod template หรือขณะ run container

| ตัวแปร | ค่าเริ่มต้น | ใช้สำหรับ |
|---|---|---|
| `TTS_PORT` | `7777` | พอร์ตของเว็บ UI/API |
| `TTS_OUTPUT_DIR` | `/workspace/outputs` | ที่เก็บเสียงที่สร้างแล้วชั่วคราว |
| `TTS_UPLOAD_DIR` | `/workspace/uploads` | ที่เก็บไฟล์อัปโหลดระหว่างประมวลผล |
| `TTS_REFERENCE_DIR` | `/workspace/reference-audio` | โฟลเดอร์ไฟล์เสียงต้นแบบที่เลือกผ่าน UI ได้ |
| `TTS_JOB_TTL_SECONDS` | `1800` | อายุไฟล์ผลลัพธ์และงานในหน่วยวินาที; 1800 คือ 30 นาที |
| `TTS_MAX_UPLOAD_BYTES` | `83886080` | ขนาดสูงสุดของไฟล์อัปโหลด; 80 MB |
| `TTS_CHECKPOINT` | MegaF5 checkpoint | เปลี่ยนตำแหน่ง checkpoint หากมีโมเดลเฉพาะ |
| `TTS_VOCAB_FILE` | MegaF5 vocabulary | เปลี่ยนตำแหน่ง vocabulary ให้ตรงกับ checkpoint |

## ข้อควรใช้เสียงอย่างรับผิดชอบ

ควรใช้เฉพาะเสียงของตนเอง หรือเสียงที่ได้รับอนุญาตชัดเจนจากเจ้าของเสียงแล้ว ห้ามใช้ระบบเพื่อแอบอ้างตัวบุคคล หลอกลวง หรือสร้างเนื้อหาที่ทำให้ผู้อื่นเสียหาย แม้ว่าระบบไม่เก็บประวัติใน UI แต่ผู้ดูแล Pod ควรจัดการ URL และสิทธิ์เข้าถึง RunPod account อย่างเหมาะสม

## การทดสอบที่ดำเนินการแล้ว

มีการทดสอบ TypeScript build ของ React UI สำเร็จ และทดสอบ FastAPI smoke test ครบเส้นทาง `/api/health`, การตรวจข้อมูลไม่ครบ, การรับไฟล์เสียงต้นแบบ, การสร้างงาน, การตรวจสถานะ และการดาวน์โหลดไฟล์ผลลัพธ์ โดยใช้ pipeline จำลองเพื่อไม่ต้องดาวน์โหลดโมเดล GPU ใน sandbox นี้ ทั้งนี้ sandbox ไม่มี Docker daemon จึงไม่สามารถ build/run image จริงได้ในสภาพแวดล้อมนี้; ขั้นตอน `docker build` และการทำ inference ด้วย GPU ควรรันทดสอบครั้งสุดท้ายในเครื่องที่มี Docker หรือบน RunPod Pod ของคุณ

## References

[1]: https://docs.runpod.io/pods/templates/create-custom-template "RunPod — Build a custom Pod template"
[2]: https://docs.runpod.io/pods/configuration/expose-ports "RunPod — Expose ports"
[3]: https://docs.runpod.io/pods/connect-to-a-pod "RunPod — Connection options"
[4]: https://github.com/biodatlab/thonburian-tts "biodatlab/thonburian-tts"
