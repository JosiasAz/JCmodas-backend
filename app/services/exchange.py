"""Política de trocas e devoluções (CDC e Decreto 7.962/2013).

Como na política de privacidade: se o lojista não escreveu a dele, a vitrine mostra este modelo já
preenchido com os dados da loja. O arrependimento de 7 dias e a garantia de 90 dias são da lei e
não dependem da loja; o prazo para troca de tamanho é escolhido em Configurações.
"""
from app.models import StoreSettings
from app.services.privacy import TEMPLATE_UPDATED, contact_line

REFUND_DAYS = 10

TEMPLATE = """## Desistiu da compra? Você tem 7 dias
Pelo Código de Defesa do Consumidor (art. 49), quem compra pela internet pode desistir em até 7 dias
corridos, contados do dia em que recebeu o pedido, sem precisar explicar o motivo.
- Avise a gente por {contact}, informando o código do pedido.
- Pedimos que a peça volte como chegou: sem sinais de uso, sem lavagem e com a etiqueta.
- O frete da devolução é por nossa conta. Combinamos com você a forma de envio.
- Devolvemos tudo o que você pagou, inclusive o frete da entrega, em até {refund_days} dias depois que a peça chegar até nós: Pix na sua chave, ou estorno na fatura do cartão.

## Não serviu? Troque em até {days} dias
Você pode trocar o tamanho, a cor ou o modelo em até {days} dias corridos depois de receber.
- A peça precisa estar sem uso, sem lavagem e com a etiqueta.
- Pode trocar pelo mesmo produto em outro tamanho ou cor, ou por outro produto da loja, pagando a diferença se ele custar mais.
- O envio da peça até nós é por sua conta, e o envio da peça nova até você é por nossa conta.{pickup}
- Cada pedido tem direito a uma troca.

## Chegou com defeito?
Você tem 90 dias, contados do recebimento, para reclamar de defeito (art. 26 do Código de Defesa do Consumidor).
Nesse caso o frete de ida e de volta é por nossa conta, e você escolhe entre trocar a peça ou receber o
dinheiro de volta.

## Como pedir
Fale com a gente por {contact} com o código do pedido (ele está na confirmação da compra e em
"Acompanhar pedido"). Respondemos em até 2 dias úteis.

## Quem vende
{seller}

Última atualização: {updated}."""


def exchange_text(store: StoreSettings, force_template: bool = False) -> str:
    if store.exchange_policy.strip() and not force_template:
        return store.exchange_policy
    seller = ", ".join(p for p in (
        store.legal_name.strip() or store.store_name,
        f"CNPJ {store.cnpj}" if store.cnpj else "",
        store.address,
    ) if p)
    return TEMPLATE.format(
        contact=contact_line(store),
        days=store.exchange_days,
        refund_days=REFUND_DAYS,
        pickup=f"\n- Se preferir, faça a troca pessoalmente na loja: {store.address}." if store.address else "",
        seller=seller,
        updated=TEMPLATE_UPDATED,
    )
