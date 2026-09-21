// n8n — Webhook POST /encerrar_atendimento
//
// Execute Workflow "ENCERRAR ATENDIMENTO MOV FIBRA V3":
//   id_cliente:       ={{ $json.body.id_cliente || $json.id_cliente }}
//   conversation_id:  ={{ $json.body.conversation_id || $json.conversation_id }}
//
// Respond to Webhook: ={{ $json }}
//
// Obs: id_cliente = ID da sessão Sofia (WhatsApp/JID), não o ID IXC.
//      O subfluxo busca ixc_id_cliente no Postgres a partir desse id.
