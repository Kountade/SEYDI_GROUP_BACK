# purchases/signals.py - COMPLET

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from .models import PurchaseReceipt, Invoice, InvoiceItem


@receiver(post_save, sender=PurchaseReceipt)
def create_invoice_from_receipt(sender, instance, created, **kwargs):
    """
    ✅ Crée automatiquement une facture lors de la création d'une réception
    """
    if not created:
        return

    if instance.invoices.exists():
        return

    # ✅ Calculer le total
    total_amount = instance.total_received_amount

    print(f"💰 TOTAL REÇU: {total_amount}")
    print(f"📦 ITEMS: {instance.items.count()}")

    if total_amount <= 0:
        print("⚠️ Montant nul, pas de facture créée")
        return

    purchase_order = instance.purchase_order

    # ✅ Générer un numéro de facture auto
    year = date.today().year
    last_invoice = Invoice.objects.filter(
        invoice_number__startswith=f"INV-AUTO-{year}-"
    ).order_by('-id').first()

    if last_invoice:
        try:
            num = int(last_invoice.invoice_number.split('-')[-1]) + 1
        except:
            num = 1
    else:
        num = 1

    auto_invoice_number = f"INV-AUTO-{year}-{num:04d}"

    # ✅ CRÉER LA FACTURE
    invoice = Invoice.objects.create(
        invoice_number=auto_invoice_number,
        agence=purchase_order.agence,
        supplier=purchase_order.supplier,
        purchase_receipt=instance,
        purchase_order=purchase_order,
        created_by=instance.received_by,
        invoice_date=instance.receipt_date or timezone.now().date(),
        due_date=timezone.now().date() + timedelta(days=30),
        invoice_type='purchase',
        is_auto_generated=True,
        notes=f"Facture auto générée depuis {instance.receipt_number}",
        status='pending',
        subtotal=total_amount,
        tax_total=Decimal('0'),
        discount=Decimal('0'),
        shipping_cost=Decimal('0'),
        total=total_amount,
        amount_paid=Decimal('0'),
        amount_remaining=total_amount
    )

    print(
        f"📄 FACTURE CRÉÉE: {invoice.invoice_number} - Total: {invoice.total}")

    # ✅ CRÉER LES LIGNES DE FACTURE
    for item in instance.items.all():
        order_item = item.order_item
        if order_item:
            InvoiceItem.objects.create(
                invoice=invoice,
                receipt_item=item,
                product=order_item.product,
                variant=order_item.variant,
                description=f"{order_item.product.name} - Commande {purchase_order.order_number}",
                quantity=item.quantity,
                unit_price=order_item.unit_price,
                discount_rate=order_item.discount_rate or Decimal('0'),
                tax_rate=Decimal('0'),
            )

    # ✅ RECALCULER LES TOTAUX
    invoice.refresh_from_db()
    subtotal = sum(item.total for item in invoice.items.all())
    invoice.subtotal = subtotal
    invoice.total = subtotal
    invoice.amount_remaining = subtotal - invoice.amount_paid
    invoice.save(update_fields=['subtotal', 'total', 'amount_remaining'])

    # ✅ METTRE À JOUR LA RÉCEPTION
    instance.is_invoiced = True
    instance.auto_invoice_number = auto_invoice_number
    instance.save(update_fields=['is_invoiced', 'auto_invoice_number'])

    print(
        f"✅ FACTURE FINALISÉE: {invoice.invoice_number} - Total: {invoice.total}")
