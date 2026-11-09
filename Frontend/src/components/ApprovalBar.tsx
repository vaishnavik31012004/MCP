interface ApprovalPayload {
  tool: string;
  arguments: Record<string, unknown>;
  risk: string;
}

export default function ApprovalBar({
  payload,
  onDecide,
}: {
  payload: ApprovalPayload;
  onDecide: (approved: boolean) => void;
}) {
  return (
    <div className="approval-bar">
      <div className="heading">
        approval needed <span className="risk-tag high">{payload.risk}</span>
      </div>
      <div className="detail">
        The agent wants to run <strong>{payload.tool}</strong> with:{" "}
        {JSON.stringify(payload.arguments)}
      </div>
      <div className="approval-actions">
        <button className="approve" onClick={() => onDecide(true)}>
          Approve
        </button>
        <button className="reject" onClick={() => onDecide(false)}>
          Reject
        </button>
      </div>
    </div>
  );
}
