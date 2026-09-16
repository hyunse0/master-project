import { NODE_LABEL, RUNNING_STAGE_NO, RUNNING_STAGE_SUB, RUNNING_STAGE_TITLE, type RunningPhase } from './stages'

interface Props {
  phase: RunningPhase
  // GET /runs/{id}/progress 폴링 결과 — 아직 첫 응답을 못 받았으면 null.
  currentNode?: string | null
}

/** POST /runs·resume 자체는 여전히 동기 호출이지만(요청 계약은 안 바꿈), 그 요청이 떠 있는
 * 동안 별도로 GET /runs/{id}/progress를 폴링해 지금 실제로 도는 노드 이름을 알아낸다
 * (useRunReview 참고) — 그래서 이 카드는 더 이상 "어느 구간"이 아니라 폴링이 성공한 동안은
 * 실제 노드 이름을 보여주고, 아직 응답을 못 받은 순간에만 구간 폴백 문구로 대체한다. */
export function RunningWorkCard({ phase, currentNode }: Props) {
  const liveLabel = currentNode ? NODE_LABEL[currentNode] : null
  return (
    <section className="running-card">
      <div className="running-card-head">
        <span className="running-spinner" />
        <h2 className="running-card-title">
          {RUNNING_STAGE_TITLE[phase]} — {liveLabel ?? `${RUNNING_STAGE_NO[phase]}단계부터`}
        </h2>
        <p className="running-card-sub">
          {liveLabel ? `지금 "${liveLabel}" 노드를 실행 중입니다.` : RUNNING_STAGE_SUB[phase]}
        </p>
      </div>
    </section>
  )
}
