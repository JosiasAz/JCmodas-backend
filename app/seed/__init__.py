"""Dados iniciais da loja.

No primeiro start (banco vazio) cria só o administrador e as configurações em branco.
Os dados de exemplo (produtos, promoções, combos, anúncios) são opcionais: veja o final do arquivo.
"""
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base, SessionLocal, schema_engine
from app.core.security import hash_password
from app.models import (
    Banner,
    Category,
    Combo,
    ComboItem,
    Coupon,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    Promotion,
    StoreSettings,
    User,
)
from app.seed.illustrations import garment_svg
from app.services.slug import slugify

SHIRT_SIZES = ["P", "M", "G", "GG"]
PANTS_SIZES = ["38", "40", "42", "44", "46"]

CATEGORIES = [
    ("Camisetas", "camiseta", "#1c1c1c"),
    ("Polos", "polo", "#1f3a5f"),
    ("Camisas", "camisa", "#dfe6ee"),
    ("Calças", "calca", "#2b3f5c"),
    ("Bermudas", "bermuda", "#b59b74"),
    ("Jaquetas e Moletons", "jaqueta", "#3d4a3a"),
    ("Acessórios", "bone", "#1c1c1c"),
]

# nome, categoria, peça, cor (nome, hex), preço, preço "de", destaque, novo, vendidos, descrição
PRODUCTS = [
    ("Camiseta Básica Algodão", "Camisetas", "camiseta", ("Preto", "#1c1c1c"), 49.9, None, True, False, 87,
     "Camiseta 100% algodão penteado, toque macio e caimento reto. A peça coringa do dia a dia."),
    ("Camiseta Básica Branca", "Camisetas", "camiseta", ("Branco", "#f7f7f5"), 49.9, None, False, False, 74,
     "Camiseta 100% algodão penteado na cor branca, gola reforçada que não deforma."),
    ("Camiseta Básica Mescla", "Camisetas", "camiseta", ("Cinza Mescla", "#9a9c9e"), 49.9, None, False, False, 51,
     "Malha mescla de algodão com poliéster, fresca e resistente."),
    ("Camiseta Estonada Vintage", "Camisetas", "camiseta", ("Verde Musgo", "#5b6449"), 69.9, 89.9, True, True, 22,
     "Lavagem estonada que deixa a cor com aspecto vintage. Modelagem levemente ampla."),
    ("Polo Piquet Clássica", "Polos", "polo", ("Marinho", "#1f3a5f"), 99.9, None, True, False, 46,
     "Polo em malha piquet com botões de madrepérola. Elegante para o trabalho e o fim de semana."),
    ("Polo Piquet Vinho", "Polos", "polo", ("Vinho", "#6b1f2a"), 99.9, None, False, True, 18,
     "A mesma polo clássica, agora na cor vinho. Combina com jeans e sarja."),
    ("Polo Listrada Premium", "Polos", "polo", ("Off White", "#ece6da"), 129.9, None, False, False, 12,
     "Polo premium com acabamento de punho canelado e tecido com elastano."),
    ("Camisa Social Slim", "Camisas", "camisa", ("Azul Claro", "#c9d9ea"), 139.9, None, True, False, 33,
     "Camisa social slim fit em tricoline, fácil de passar. Ideal para o escritório."),
    ("Camisa Linho Manga Longa", "Camisas", "camisa", ("Areia", "#d8ccb4"), 179.9, 219.9, True, True, 9,
     "Linho com viscose, leve e fresco, perfeito para dias quentes com estilo."),
    ("Camisa Xadrez Flanela", "Camisas", "camisa", ("Vermelho", "#8c2f2f"), 149.9, None, False, False, 15,
     "Flanela macia em xadrez clássico. Use fechada ou aberta sobre uma camiseta."),
    ("Calça Jeans Slim", "Calças", "calca", ("Jeans Escuro", "#2b3f5c"), 159.9, None, True, False, 58,
     "Jeans com elastano, lavagem escura e corte slim que não aperta."),
    ("Calça Sarja Chino", "Calças", "calca", ("Caqui", "#b59b74"), 149.9, None, False, False, 27,
     "Calça chino em sarja com elastano. Versátil do casual ao social."),
    ("Calça Jogger Moletinho", "Calças", "calca", ("Grafite", "#3b3d40"), 119.9, None, False, True, 14,
     "Jogger com punho na barra e cordão, confortável para o dia a dia."),
    ("Bermuda Sarja", "Bermudas", "bermuda", ("Bege", "#c8b591"), 89.9, None, True, False, 41,
     "Bermuda de sarja com bolsos faca e comprimento na altura do joelho."),
    ("Bermuda Jeans", "Bermudas", "bermuda", ("Jeans Médio", "#4d6a8f"), 99.9, 119.9, False, False, 23,
     "Bermuda jeans com lavagem média e barra dobrada."),
    ("Jaqueta Corta-Vento", "Jaquetas e Moletons", "jaqueta", ("Verde Militar", "#3d4a3a"), 199.9, None, True, True, 8,
     "Jaqueta leve, repele água e cabe na mochila. Forro em tela respirável."),
    ("Moletom Canguru", "Jaquetas e Moletons", "moletom", ("Preto", "#1c1c1c"), 169.9, 199.9, False, False, 19,
     "Moletom flanelado por dentro, com capuz e bolso canguru."),
    ("Boné Aba Curva", "Acessórios", "bone", ("Preto", "#1c1c1c"), 59.9, None, False, False, 31,
     "Boné com regulagem traseira e aba curva. Logo JC bordado."),
]

BACKGROUNDS = ["#f2f0eb", "#eceff1", "#efece6", "#e9ece8"]


def _write_image(name: str, kind: str, color: str, background: str) -> str:
    folder = Path(settings.upload_dir) / "seed"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.svg").write_text(garment_svg(kind, color, background), encoding="utf-8")
    return f"/static/uploads/seed/{name}.svg"


def _variants(category: str, color: str, index: int) -> list[ProductVariant]:
    if category == "Acessórios":
        return [ProductVariant(size="U", color=color, stock=12)]
    sizes = PANTS_SIZES if category in ("Calças", "Bermudas") else SHIRT_SIZES
    # estoques variados (alguns baixos, para o painel mostrar o alerta)
    # um tamanho esgotado na primeira peça para o painel mostrar o alerta
    return [ProductVariant(size=s, color=color, stock=0 if (index, i) == (0, 0) else (index * 7 + i * 5) % 14 + 1)
            for i, s in enumerate(sizes)]


def seed_base(db: Session) -> None:
    """Loja vazia: só o administrador (dados do .env) e as configurações em branco."""
    if not settings.admin_password or len(settings.admin_password) < 8:
        raise RuntimeError(
            "Banco sem nenhum usuário: defina ADMIN_EMAIL e ADMIN_PASSWORD (8+ caracteres) no .env "
            "para criar o primeiro administrador. Depois de criado, apague ADMIN_PASSWORD do arquivo."
        )
    db.add(User(name="Administrador", email=settings.admin_email.lower(),
                password_hash=hash_password(settings.admin_password)))
    if db.get(StoreSettings, 1) is None:
        db.add(StoreSettings(id=1, store_name="JC Moda Masculina"))
    db.commit()


def seed_demo(db: Session) -> None:
    """Catálogo, promoções, combos e anúncios fictícios, para testar ou demonstrar a loja."""
    now = datetime.now()

    store = db.get(StoreSettings, 1) or StoreSettings(id=1)
    for key, value in dict(
        store_name="JC Moda Masculina",
        announcement="Frete grátis acima de R$ 299 · 5% OFF no Pix · Parcele em até 6x sem juros",
        whatsapp="5592999999999",
        instagram="jcmodamasculina",
        email="contato@jcmoda.com.br",
        address="Avenida Exemplo, 123 - Centro, Manaus/AM - CEP 69005-040",
        opening_hours="Seg a Sáb, 9h às 19h",
        shipping_fee=14.9,
        shipping_state_fee=24.9,
        shipping_other_fee=39.9,
        free_shipping_min=299,
        pix_discount_percent=5,
        pix_key="contato@jcmoda.com.br",
        max_installments=6,
        pickup_enabled=True,
    ).items():
        setattr(store, key, value)
    db.add(store)

    categories = {}
    for sort, (name, kind, color) in enumerate(CATEGORIES):
        slug = slugify(name)
        categories[name] = Category(name=name, slug=slug, sort=sort,
                                    image=_write_image(f"categoria-{slug}", kind, color, "#ece9e2"))
    db.add_all(categories.values())

    products = {}
    for i, (name, cat, kind, (color_name, hex_color), price, old, featured, new, sold, desc) in enumerate(PRODUCTS):
        slug = slugify(name)
        products[name] = Product(
            name=name, slug=slug, description=desc, price=price, compare_at_price=old,
            category=categories[cat], featured=featured, is_new=new, sold_count=sold,
            images=[_write_image(slug, kind, hex_color, BACKGROUNDS[i % len(BACKGROUNDS)]),
                    _write_image(f"{slug}-2", kind, hex_color, "#e4e1da")],
            variants=_variants(cat, color_name, i),
        )
    db.add_all(products.values())
    db.flush()

    db.add_all([
        Promotion(name="Semana das Polos", badge="20% OFF", kind="percent", value=20,
                  scope="category", category_id=categories["Polos"].id,
                  starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=6)),
        Promotion(name="Leve 3 Pague 2 em Camisetas", badge="Leve 3 Pague 2", kind="buy_x_pay_y",
                  buy_qty=3, pay_qty=2, scope="category", category_id=categories["Camisetas"].id),
        Promotion(name="Queima de Bermudas", badge="R$ 15 OFF", kind="fixed", value=15,
                  scope="products", product_ids=[products["Bermuda Sarja"].id],
                  ends_at=now + timedelta(days=10)),
    ])

    db.add_all([
        Coupon(code="BEMVINDO10", description="10% na primeira compra", kind="percent", value=10),
        Coupon(code="JC30", description="R$ 30 OFF em compras acima de R$ 250", kind="fixed", value=30,
               min_order=250),
        Coupon(code="FRETEGRATIS", description="Frete grátis acima de R$ 150", kind="free_shipping",
               min_order=150, max_uses=100),
    ])

    db.add_all([
        Combo(name="Kit 3 Camisetas Básicas", slug="kit-3-camisetas-basicas", price=119.9,
              description="Escolha o tamanho de cada uma: preta, branca e mescla. Economia garantida!",
              image=_write_image("combo-camisetas", "camiseta", "#1c1c1c", "#e9e6df"),
              items=[ComboItem(product=products["Camiseta Básica Algodão"]),
                     ComboItem(product=products["Camiseta Básica Branca"]),
                     ComboItem(product=products["Camiseta Básica Mescla"])]),
        Combo(name="Look Trabalho", slug="look-trabalho", price=259.9,
              description="Camisa social slim + calça sarja chino. Pronto para a semana.",
              image=_write_image("combo-trabalho", "camisa", "#c9d9ea", "#e6e9ec"),
              items=[ComboItem(product=products["Camisa Social Slim"]),
                     ComboItem(product=products["Calça Sarja Chino"])]),
        Combo(name="Kit Fim de Semana", slug="kit-fim-de-semana", price=169.9,
              description="Polo piquet clássica + bermuda sarja para curtir o sábado.",
              image=_write_image("combo-fds", "polo", "#1f3a5f", "#ece8df"),
              items=[ComboItem(product=products["Polo Piquet Clássica"]),
                     ComboItem(product=products["Bermuda Sarja"])]),
    ])

    db.add_all([
        Banner(title="Nova coleção chegou", subtitle="Peças pensadas para o homem que se veste bem todos os dias.",
               cta_label="Ver novidades", link="/loja?ordem=newest", placement="hero", sort=0,
               bg_color="#111111", text_color="#ffffff",
               image=_write_image("banner-colecao", "jaqueta", "#3d4a3a", "#2a2a2a")),
        Banner(title="Semana das Polos: 20% OFF", subtitle="Todas as polos com desconto até domingo.",
               cta_label="Aproveitar", link="/loja?categoria=polos", placement="hero", sort=1,
               bg_color="#1f3a5f", text_color="#ffffff",
               image=_write_image("banner-polos", "polo", "#ece6da", "#2a4670")),
        Banner(title="Leve 3, pague 2", subtitle="Em todas as camisetas. Misture cores e tamanhos.",
               cta_label="Montar meu kit", link="/loja?categoria=camisetas", placement="hero", sort=2,
               bg_color="#ece6da", text_color="#111111",
               image=_write_image("banner-camisetas", "camiseta", "#1c1c1c", "#e0d8c8")),
        Banner(title="Frete grátis acima de R$ 299", subtitle="E 5% de desconto pagando no Pix.",
               cta_label="Comprar agora", link="/loja", placement="strip", bg_color="#111111"),
        Banner(title="Combos com até 20% OFF", subtitle="Kits prontos que saem mais em conta.",
               cta_label="Ver combos", link="/combos", placement="card", sort=0,
               bg_color="#e9e4da", text_color="#111111"),
        Banner(title="Use o cupom BEMVINDO10", subtitle="10% de desconto na sua primeira compra.",
               cta_label="Ir para a loja", link="/loja", placement="card", sort=1,
               bg_color="#1f3a5f", text_color="#ffffff"),
    ])
    db.commit()


def seed_if_empty() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is None:
            seed_base(db)


def clear_store(db: Session) -> None:
    """Apaga catálogo, marketing e pedidos e zera os contatos. Usuários do painel são mantidos."""
    for model in (OrderItem, Order, ComboItem, Combo, ProductVariant, Product, Promotion, Coupon, Banner, Category):
        db.execute(delete(model))
    store = db.get(StoreSettings, 1)
    if store:
        db.delete(store)
        db.flush()
    db.add(StoreSettings(id=1, store_name="JC Moda Masculina"))
    db.commit()
    shutil.rmtree(Path(settings.upload_dir) / "seed", ignore_errors=True)


def main() -> None:
    # python -m app.seed            cria as tabelas e o administrador (se não existir)
    # python -m app.seed --demo     adiciona os produtos/promoções de exemplo
    # python -m app.seed --clear    apaga produtos, promoções, pedidos e contatos (mantém os usuários)
    # python -m app.seed --reset    apaga TUDO, inclusive usuários, e recria do zero
    # --clear e --reset no banco de produção exigem também --confirm-production
    destructive = [flag for flag in ("--reset", "--clear") if flag in sys.argv]
    if destructive and settings.points_to_production_db and "--confirm-production" not in sys.argv:
        sys.exit(
            f"Recusado: {' '.join(destructive)} apagaria dados do banco de PRODUÇÃO "
            f"(ENVIRONMENT={settings.environment}, NEON_BRANCH={settings.neon_branch}). "
            "Use um banco de desenvolvimento (neon checkout dev) ou, se tiver certeza, "
            "repita o comando com --confirm-production."
        )
    if "--reset" in sys.argv:
        Base.metadata.drop_all(schema_engine)
    Base.metadata.create_all(schema_engine)
    seed_if_empty()
    with SessionLocal() as db:
        if "--clear" in sys.argv:
            clear_store(db)
            print("Loja limpa.")
        if "--demo" in sys.argv:
            if db.scalar(select(Product.id).limit(1)) is not None:
                sys.exit("A loja já tem produtos. Use --clear --demo para trocar pelos de exemplo.")
            seed_demo(db)
            print("Dados de exemplo adicionados.")
    print("Banco pronto.")
