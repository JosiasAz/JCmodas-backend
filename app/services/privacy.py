"""Política de privacidade da loja (LGPD).

Se o lojista ainda não escreveu a dele em Configurações, a vitrine mostra este modelo preenchido
com os dados da loja. Os trechos entre colchetes precisam ser completados pelo lojista.
"""
from app.models import StoreSettings

TEMPLATE = """## Quem somos
{store_name} ("nós") é a controladora dos dados pessoais tratados nesta loja virtual.
CNPJ: [preencha]. Contato para assuntos de privacidade (encarregado): {contact}.

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
Os dados do pedido são mantidos pelo prazo exigido pela legislação fiscal. Depois de [12] meses da
entrega, nome, telefone, e-mail e endereço são anonimizados; ficam apenas os valores e produtos.

## Seus direitos
Você pode pedir a confirmação, o acesso, a correção, a anonimização ou a exclusão dos seus dados,
além de informações sobre o compartilhamento, pelo contato {contact}. Responderemos em até 15 dias.

## Segurança
Usamos conexão criptografada, acesso restrito ao painel com verificação em duas etapas e registro
das alterações feitas. Em caso de incidente que possa trazer risco a você, avisaremos você e a ANPD.

## Cookies e armazenamento no navegador
O site guarda no seu navegador o carrinho de compras e, só se você marcar "lembrar meus dados",
os dados do checkout. Você pode apagá-los limpando os dados do site no navegador.

Última atualização: [data]."""


def privacy_text(store: StoreSettings, force_template: bool = False) -> str:
    if store.privacy_policy.strip() and not force_template:
        return store.privacy_policy
    contacts = [c for c in (store.email, f"WhatsApp {store.whatsapp}" if store.whatsapp else "") if c]
    return TEMPLATE.format(
        store_name=store.store_name or "[nome da loja]",
        contact=" / ".join(contacts) or "[e-mail ou WhatsApp de contato]",
    )
