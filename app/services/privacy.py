"""Política de privacidade da loja (LGPD).

Se o lojista ainda não escreveu a dele em Configurações, a vitrine mostra este modelo, já completo e
preenchido com os dados da loja (nome, endereço e contato). O lojista não precisa mexer em nada.
"""
from app.models import StoreSettings

# pedidos entregues/cancelados há mais tempo que isso perdem os dados pessoais (limpeza automática diária)
RETENTION_MONTHS = 12
TEMPLATE_UPDATED = "outubro de 2026"

TEMPLATE = """## Quem somos
{store_name} ("nós") é a responsável (controladora) pelos dados pessoais tratados nesta loja virtual{address}.
Contato para assuntos de privacidade (encarregado): {contact}.

## Quais dados coletamos
- Para entregar e acompanhar o seu pedido: nome, telefone/WhatsApp, e-mail (opcional) e endereço de entrega.
- Dados do pedido: produtos, valores, forma de pagamento e observações que você escrever.
- Dados técnicos mínimos para segurança, como o endereço IP de quem acessa o painel da loja.
Não coletamos nem armazenamos dados de cartão.

## Para que usamos
- Processar, entregar e dar suporte ao seu pedido (base legal: execução de contrato, art. 7º, V, da LGPD).
- Cumprir obrigações fiscais e legais (art. 7º, II).
- Proteger a loja contra fraudes e abusos (legítimo interesse, art. 7º, IX).
Não vendemos seus dados e não enviamos propaganda sem o seu pedido.

## Com quem compartilhamos
- WhatsApp: quando você escolhe enviar o pedido ou falar com a gente por lá.
- ViaCEP: o CEP digitado no checkout é consultado para preencher o endereço.
- Provedores de hospedagem e banco de dados que mantêm o site funcionando (ex.: Neon), sob contrato.
- Transportadora ou entregador, apenas o necessário para a entrega.

## Por quanto tempo guardamos
Guardamos os dados do pedido enquanto ele está em andamento e por até {months} meses depois de entregue ou
cancelado, para trocas, garantia e atendimento. Depois disso, nome, telefone, e-mail e endereço são
apagados automaticamente; ficam apenas os valores e os produtos, para o controle de vendas da loja.

## Seus direitos
Você pode pedir a confirmação, o acesso, a correção, a anonimização ou a exclusão dos seus dados,
além de informações sobre o compartilhamento, pelo contato {contact}. Responderemos em até 15 dias.

## Segurança
Usamos conexão criptografada, acesso restrito ao painel com verificação em duas etapas e registro
das alterações feitas. Em caso de incidente que possa trazer risco a você, avisaremos você e a ANPD.

## Cookies e armazenamento no navegador
O site guarda no seu navegador o carrinho de compras e, só se você marcar "lembrar meus dados",
os dados do checkout. Você pode apagá-los limpando os dados do site no navegador.

Última atualização: {updated}."""


def format_phone(digits: str) -> str:
    """5592993299773 -> +55 (92) 99329-9773 (números de fora do Brasil ficam só com o +)."""
    if digits.startswith("55") and len(digits) in (12, 13):
        ddd, num = digits[2:4], digits[4:]
        return f"+55 ({ddd}) {num[:-4]}-{num[-4:]}"
    return f"+{digits}"


def privacy_text(store: StoreSettings, force_template: bool = False) -> str:
    if store.privacy_policy.strip() and not force_template:
        return store.privacy_policy
    contacts = [c for c in (store.email, f"WhatsApp {format_phone(store.whatsapp)}" if store.whatsapp else "") if c]
    return TEMPLATE.format(
        store_name=store.store_name or "Esta loja",
        address=f", com endereço em {store.address}" if store.address else "",
        contact=" / ".join(contacts) or "os canais de atendimento informados no site",
        months=RETENTION_MONTHS,
        updated=TEMPLATE_UPDATED,
    )
