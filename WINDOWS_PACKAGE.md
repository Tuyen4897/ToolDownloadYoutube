# Đóng gói `auto_follow` thành file `.exe` (Windows)

## 1. Chuẩn bị môi trường
- Cài đặt Python 3 mới nhất từ [python.org](https://www.python.org/downloads/) và tick “Add python.exe to PATH”.
- Cài `ffmpeg` (bằng `choco install ffmpeg` hoặc tải file ZIP, giải nén và thêm vào `PATH`).
- Mở PowerShell và chuyển tới thư mục dự án:
  ```powershell
  cd C:\Users\<user>\sbase\linh-tinh\Tool
  ```

## 2. Tạo file `.exe` bằng script dựng sẵn
Chạy:
```powershell
.\build_windows_exe.ps1
```

Script sẽ:
- Tạo virtualenv tạm `.venv-build` (xóa với `.\build_windows_exe.ps1 -Clean` nếu muốn rebuild sạch).
- Cài `yt-dlp`, `requests`, `pyinstaller`.
- Gọi PyInstaller tạo `dist\auto_follow.exe`.
- Sao chép `channels.json` thành `dist\channels.sample.json` để dùng làm mẫu cấu hình.

## 3. Kiểm tra kết quả
- Folder `dist` sẽ chứa `auto_follow.exe`, `channels.sample.json`, `auto_follow.exe` cần thêm `ffmpeg.exe` (copy vào đây hoặc đảm bảo có trong PATH).
- Chạy thử:
  ```powershell
  cd dist
  .\auto_follow.exe --config channels.sample.json --download-dir C:\Videos
  ```

## 4. Phân phối / Triển khai
- Gói toàn bộ nội dung `dist/` (cùng `ffmpeg.exe` nếu muốn) vào file ZIP để chuyển sang máy khác.
- Người nhận chỉ cần chỉnh `channels.sample.json` (đổi tên thành `channels.json` nếu muốn), rồi chạy:
  ```powershell
  auto_follow.exe --config channels.json --download-dir C:\Videos
  ```
- Thiết lập Task Scheduler gọi `auto_follow.exe` theo chu kỳ mong muốn (xem hướng dẫn task trong phần trước).

> Ghi chú: Nếu chỉnh sửa mã nguồn, chỉ cần chạy lại `.\build_windows_exe.ps1` để tạo bản `.exe` mới.

