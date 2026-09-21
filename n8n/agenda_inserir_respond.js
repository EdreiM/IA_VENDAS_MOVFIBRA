// n8n — Execute Workflow "INSERE AGENDA TÉCNICOS NA OS MOV FIBRA V3"
// Mapeamento dos inputs (Webhook POST → subfluxo):
//
// ixc_id_cliente:        ={{ $json.body.ixc_id_cliente || $json.ixc_id_cliente }}
// data_hora_agendamento: ={{ $json.body.data_hora_agendamento || $json.data_hora_agendamento }}
// id_tecnico:            ={{ $json.body.id_tecnico || $json.id_tecnico }}
//
// Respond to Webhook: ={{ $json }}
