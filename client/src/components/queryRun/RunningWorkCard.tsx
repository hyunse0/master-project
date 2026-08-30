import { RUNNING_STAGE_NO, RUNNING_STAGE_SUB, RUNNING_STAGE_TITLE, type RunningPhase } from './stages'

interface Props {
  phase: RunningPhase
}

/** POST /runs·resume은 동기 호출이라 요청이 떠 있는 동안 노드별 실시간 데이터는 없다
 * (스트리밍 미구현 — 계획 문서에서도 별도 작업으로 보류됨). 그래서 이 카드는 "지금 어느
 * 구간의 요청이 진행 중인가"만 정직하게 보여준다 — 없는 중간 데이터를 지어내 리플레이하지
 * 않는다. 요청이 끝나면 실제 결과 데이터로 검토/결과 카드가 뜬다. */
export function RunningWorkCard({ phase }: Props) {
  return (
    <section className="running-card">
      <div className="running-card-head">
        <span className="running-spinner" />
        <h2 className="running-card-title">
          {RUNNING_STAGE_TITLE[phase]} — {RUNNING_STAGE_NO[phase]}단계부터
        </h2>
        <p className="running-card-sub">{RUNNING_STAGE_SUB[phase]}</p>
      </div>
    </section>
  )
}
