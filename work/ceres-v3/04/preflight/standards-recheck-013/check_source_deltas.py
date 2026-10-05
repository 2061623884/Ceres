import hashlib, json, re, zipfile
from pathlib import Path
repo=Path(r'C:\Users\20616\Desktop\Agent\Agent产品\Ceres')
zip_path=repo/'work/ceres-v3/04/review-v1/review-source.zip'
checks={}
with zipfile.ZipFile(zip_path) as z:
    old_chat=z.read('backend/app/services/chat_opening_service.py')
    current_chat=(repo/'backend/app/services/chat_opening_service.py').read_bytes()
    old_demo=z.read('work/ceres-v3/03/demo.html')
    current_demo=(repo/'work/ceres-v3/03/demo.html').read_bytes()
    old_chat_lines=old_chat.splitlines(keepends=True)
    normalized_chat=[]
    skipped=0
    i=0
    while i < len(old_chat_lines):
        line=old_chat_lines[i]
        if b'if self._openings.get(opening_id) is not opening:' in line:
            if i+1 >= len(old_chat_lines) or b'raise AppError(404, "OPENING_NOT_FOUND"' not in old_chat_lines[i+1]:
                raise SystemExit('close guard hunk differs from expected two lines')
            skipped+=2
            i+=2
            continue
        normalized_chat.append(line)
        i+=1
    normalized_chat_bytes=b''.join(normalized_chat)
    old_demo_text=old_demo.decode('utf-8')
    current_demo_text=current_demo.decode('utf-8')
    normalized_demo_text=re.sub(r'\brestoreChatState\b','sync',current_demo_text)
    checks={
      'review_v1_zip_sha256': hashlib.sha256(zip_path.read_bytes()).hexdigest(),
      'old_chat_sha256': hashlib.sha256(old_chat).hexdigest(),
      'current_chat_sha256': hashlib.sha256(current_chat).hexdigest(),
      'close_guard_removed_exactly_two_lines': skipped==2,
      'chat_opening_service_normalizes_to_review_v1': normalized_chat_bytes==current_chat,
      'old_demo_sha256': hashlib.sha256(old_demo).hexdigest(),
      'current_demo_sha256': hashlib.sha256(current_demo).hexdigest(),
      'restore_name_occurrences': len(re.findall(r'\brestoreChatState\b',current_demo_text)),
      'demo_only_identifier_change': normalized_demo_text==old_demo_text,
    }
    (repo/'work/ceres-v3/04/preflight/standards-recheck-013/source-delta-check.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(checks,ensure_ascii=False,indent=2))
if not checks['chat_opening_service_normalizes_to_review_v1'] or not checks['demo_only_identifier_change'] or checks['restore_name_occurrences'] != 5:
    raise SystemExit(1)
