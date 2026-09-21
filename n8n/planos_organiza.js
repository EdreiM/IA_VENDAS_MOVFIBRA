// Cole no no Code do n8n (Run Once for All Items)
// No antes: Webhook + Postgres

// Contexto opcional (cidade/bairro) — nao usa $('Node') para evitar erro no n8n
var ctx = {};

function num(v) {
  if (v === null || v === undefined || v === '') return null;
  var n = Number(String(v).replace(',', '.'));
  return isFinite(n) ? n : null;
}

function gerarTags(p) {
  var t = (p.nome + ' ' + (p.descricao || '') + ' ' + (p.beneficios || '')).toLowerCase();
  var tags = [];

  function add() {
    for (var i = 0; i < arguments.length; i++) {
      if (tags.indexOf(arguments[i]) === -1) tags.push(arguments[i]);
    }
  }

  if (t.indexOf('essencial') >= 0) add('essencial');
  if (t.indexOf('one+') >= 0 || t.indexOf('one plus') >= 0) add('one_plus');
  if (t.indexOf('up+') >= 0) add('up_plus');
  if (t.indexOf('infinity') >= 0) add('infinity');
  if (t.indexOf('super+') >= 0) add('super_plus');
  else if (t.indexOf('super') >= 0) add('super');
  if (t.indexOf('combo') >= 0) add('combo');

  if (t.indexOf('12 gb') >= 0 || t.indexOf('12gb') >= 0) add('chip_12gb');
  if (t.indexOf('22 gb') >= 0 || t.indexOf('22gb') >= 0) add('chip_22gb');
  if (t.indexOf('chip') >= 0) add('chip');

  if (t.indexOf('mesh') >= 0) add('mesh');
  if (t.indexOf('exitlag') >= 0 || t.indexOf('jogo') >= 0) add('games', 'exitlag');
  if (t.indexOf('telemedicina') >= 0) add('telemedicina');
  if (t.indexOf('kaspersky') >= 0) add('kaspersky');
  if (t.indexOf('disney') >= 0) add('disney');
  if (t.indexOf('max') >= 0 || t.indexOf('hbo') >= 0) add('max');
  if (t.indexOf('globoplay') >= 0) add('globoplay');
  if (t.indexOf('prime') >= 0) add('prime');
  if (t.indexOf('deezer') >= 0) add('deezer');
  if (t.indexOf('looke') >= 0) add('looke');
  if (t.indexOf('pontualidade') >= 0) add('pontualidade');

  var valor = num(p.valor);
  if (valor !== null) {
    if (valor <= 129) add('economico', 'mais_barato');
    if (valor >= 189) add('premium', 'top');
    if (valor === 139) add('faixa_139');
  }

  var disp = num(p.dispositivos_max);
  if (disp !== null) {
    if (disp >= 12) add('muitos_dispositivos');
    if (disp <= 4) add('poucos_dispositivos');
  }

  add('fibra');
  if (tags.indexOf('combo') >= 0 || tags.indexOf('chip') >= 0) {
    tags = tags.filter(function (x) { return x !== 'fibra'; });
    add('combo_internet_chip');
  }

  return tags;
}

var rows = $input.all();
var planos = [];

for (var j = 0; j < rows.length; j++) {
  var p = rows[j].json;
  if (p.ativo === false || p.ativo === 0) continue;

  var valor = num(p.valor);
  var valorPont = num(p.valor_pontualidade);
  var dispMax = p.dispositivos_max;
  if (dispMax === null || dispMax === undefined) dispMax = p.max_dispositivos;

  planos.push({
    id: Number(p.id),
    nome: String(p.nome || '').trim(),
    velocidade: p.velocidade || 'Ilimitada',
    modalidade: p.modalidade || 'mensal',
    requer_cartao: !!p.requer_cartao,
    valor: valor,
    parcelas: num(p.parcelas),
    descricao: p.descricao || '',
    dispositivos_max: num(dispMax),
    beneficios: p.beneficios || '',
    ordem: Number(p.ordem != null ? p.ordem : 100),
    ativo: true,
    destaque: !!p.destaque,
    valor_pontualidade: valorPont,
    condicao_valor_pontualidade: p.condicao_valor_pontualidade || null,
    tags: gerarTags(p),
  });
}

planos.sort(function (a, b) {
  if (a.destaque !== b.destaque) return a.destaque ? -1 : 1;
  if (a.ordem !== b.ordem) return a.ordem - b.ordem;
  if (a.valor !== b.valor) return (a.valor || 0) - (b.valor || 0);
  return a.nome.localeCompare(b.nome);
});

var destaque = null;
for (var k = 0; k < planos.length; k++) {
  if (planos[k].destaque) {
    destaque = planos[k];
    break;
  }
}
if (!destaque && planos.length > 0) destaque = planos[0];

return [{
  json: {
    ok: planos.length > 0,
    total: planos.length,
    plano_destaque_id: destaque ? destaque.id : null,
    contexto_recebido: ctx,
    planos: planos,
    motivo: planos.length ? '' : 'Nenhum plano ativo',
  },
}];
