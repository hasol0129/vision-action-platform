"""대표 Frame에 사람별 Skeleton과 예측 결과를 그려 base64 JPEG로 돌려준다 (추가 점수: Skeleton Overlay)."""
from __future__ import annotations

import base64

import cv2
import numpy as np

from services.pose_pipeline import KeyFrame
from src.pose_utils import COCO_SKELETON

MINT = (192, 224, 62)       # #3ee0c0 (BGR)
INDIGO = (216, 63, 59)      # #3b3fd8
AMBER = (11, 158, 245)      # #f59e0b
WHITE = (255, 255, 255)
MAX_WIDTH = 960
KP_MIN_CONF = 0.5


def _label(img, text, x, y, color):
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
    (w, h), base = cv2.getTextSize(text, font, scale, thick)
    x = int(max(0, min(x, img.shape[1] - w - 12)))
    y = int(max(h + 10, y))
    cv2.rectangle(img, (x, y - h - 10), (x + w + 12, y + base - 2), color, -1, cv2.LINE_AA)
    cv2.putText(img, text, (x + 6, y - 5), font, scale, WHITE, thick, cv2.LINE_AA)


def render_keyframe(keyframe: KeyFrame | None, predictions: list[dict], quality: int = 85) -> str | None:
    if keyframe is None:
        return None

    img = keyframe.frame.copy()
    scale = 1.0
    if img.shape[1] > MAX_WIDTH:
        scale = MAX_WIDTH / img.shape[1]
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    # 화면을 살짝 어둡게 해서 Skeleton이 잘 보이게 한다
    img = cv2.addWeighted(img, 0.82, np.zeros_like(img), 0.18, 0)
    by_track = {p['track_id']: p for p in predictions}
    stroke = max(2, int(round(img.shape[1] / 320)))

    for track_id, xy, conf, box in keyframe.people:
        pts = xy * scale
        visible = conf >= KP_MIN_CONF

        for a, b in COCO_SKELETON:
            if visible[a] and visible[b]:
                cv2.line(img, tuple(np.int32(pts[a])), tuple(np.int32(pts[b])), MINT, stroke + 1, cv2.LINE_AA)
        for i, p in enumerate(pts):
            if visible[i]:
                c = tuple(np.int32(p))
                cv2.circle(img, c, stroke + 3, WHITE, -1, cv2.LINE_AA)
                cv2.circle(img, c, stroke + 1, MINT, -1, cv2.LINE_AA)

        x1, y1, x2, y2 = (box * scale).astype(int)
        cv2.rectangle(img, (x1, y1), (x2, y2), MINT, 1, cv2.LINE_AA)

        pred = by_track.get(track_id)
        if pred is None:
            _label(img, f'#{track_id}  not analyzed', x1, y1 - 4, (120, 120, 120))
        else:
            color = AMBER if pred['is_uncertain'] else INDIGO
            _label(img, f"#{track_id}  {pred['action_label']}  {pred['confidence'] * 100:.0f}%", x1, y1 - 4, color)

    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode('ascii') if ok else None
