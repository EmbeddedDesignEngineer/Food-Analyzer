import asyncio
import time

from src.services.nutrition_cache import NutritionCache



semaphore = asyncio.Semaphore(10)


async def lookup_with_cache(ingredient, provider, cache: NutritionCache, loop):

    original_name = ingredient.name

    facts = cache.get(original_name)
    if facts is not None:
        return original_name, facts

    async with semaphore:
        try:
            facts = await loop.run_in_executor(None, provider.lookup, original_name)
        except Exception:

            facts = await loop.run_in_executor(None, provider.lookup, original_name)


    cache.set(original_name, facts)
    return original_name, facts


async def fetch_all_nutrition(ingredients, provider, cache: NutritionCache):

    loop = asyncio.get_running_loop()

    results = await asyncio.gather(
        *[lookup_with_cache(ing, provider, cache, loop) for ing in ingredients],
        return_exceptions=True
    )

    facts_by_name = {}
    failed = []
    for item in results:
        if isinstance(item, Exception):
            failed.append(item)
        else:
            name, facts = item
            facts_by_name[name] = facts

    return facts_by_name, failed


async def fetch_sequential(ingredients, provider, cache: NutritionCache):

    loop = asyncio.get_running_loop()
    facts_by_name = {}
    failed = []
    for ing in ingredients:
        original_name = ing.name
        facts = cache.get(original_name)
        if facts is None:
            try:
                facts = await loop.run_in_executor(None, provider.lookup, original_name)
            except Exception as e:
                failed.append(e)
                continue
            cache.set(original_name, facts)
        facts_by_name[original_name] = facts
    return facts_by_name, failed


if __name__ == "__main__":


    class FakeIngredient:
        def __init__(self, name):
            self.name = name

    from ai import NutritionFacts

    class FakeProvider:
        def lookup(self, name):  # sync, blocking — like the real provider
            time.sleep(2)
            if name == "xiyar":
                raise ValueError(f"{name} üçün API xetasi")
            return NutritionFacts(
                name=name,
                kcal_per_100g=100,
                protein_g_per_100g=10,
                carbs_g_per_100g=20,
                fat_g_per_100g=5,
            )

    async def main():
        ingredients = [FakeIngredient(n) for n in
                        ["toyuq", "düyü", "xiyar", "pomidor", "kartof", "baliq", "yumurta"]]
        provider = FakeProvider()
        cache = NutritionCache(ttl_seconds=86400)

        start_seq = time.time()
        facts_seq, failed_seq = await fetch_sequential(ingredients, provider, cache)
        print(f"Ardıcıl vaxt: {time.time() - start_seq:.2f} saniyə")
        print("facts_by_name (ardıcıl):", facts_seq)
        print("failed (ardıcıl):", failed_seq)

        cache2 = NutritionCache(ttl_seconds=86400)  # təzə cache, ədalətli müqayisə üçün
        print()

        start_par = time.time()
        facts_par, failed_par = await fetch_all_nutrition(ingredients, provider, cache2)
        print(f"Paralel vaxt: {time.time() - start_par:.2f} saniyə")
        print("facts_by_name (paralel):", facts_par)
        print("failed (paralel):", failed_par)

    asyncio.run(main())
