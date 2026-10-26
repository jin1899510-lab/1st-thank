"""원본 시간 ↔ 편집 타임라인 시간 계산 (잘라낸 구간을 빼고 이어 붙인 기준)."""

MIN_PIECE = 0.3  # 이보다 짧은 영상 조각·자막은 버림(초)


def subtract(ranges, cuts):
    """ranges 에서 cuts 구간을 빼고, 너무 짧은 조각은 버린다."""
    out = []
    for s, e in ranges:
        pieces = [(s, e)]
        for cs, ce in cuts:
            nxt = []
            for ps, pe in pieces:
                if ce <= ps or cs >= pe:
                    nxt.append((ps, pe))
                    continue
                if cs > ps:
                    nxt.append((ps, cs))
                if ce < pe:
                    nxt.append((ce, pe))
            pieces = nxt
        out += [(ps, pe) for ps, pe in pieces if pe - ps >= MIN_PIECE]
    return sorted(out)


class TimeMap:
    """원본 시간 ↔ 타임라인 시간 변환 (남긴 조각들을 이어 붙인 기준)."""

    def __init__(self, pieces):
        self.pieces, t = [], 0.0
        for s, e in pieces:
            self.pieces.append((s, e, t))
            t += e - s
        self.total = t

    def span(self, s, e):
        """원본 구간 [s,e] 가 타임라인에서 차지하는 [시작,끝]. 남긴 조각과 겹치지 않으면 None."""
        hits = [(max(s, ps) - ps + t, min(e, pe) - ps + t) for ps, pe, t in self.pieces if min(e, pe) > max(s, ps)]
        if not hits:
            return None
        return hits[0][0], hits[-1][1]


def no_overlap(spans):
    out, prev = [], 0.0
    for s, e, payload in sorted(spans, key=lambda x: x[0]):
        s = max(s, prev)
        if e - s >= MIN_PIECE:
            out.append((s, e, payload))
            prev = e
    return out
