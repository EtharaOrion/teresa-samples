# Ground truth

Repository: `hibernate/hibernate-orm`
Base commit: `a512ede38b693769d8fd801a23c5c7b640df6f7f` (immediate first parent of merge commit
`5448e8b62841e952cabd0d26931718bad4ad2473`, which merged PR #263)
Language: Java

## The behaviour at `base_commit`

Every statement that Envers generates for reading a historical association is written with fixed single-letter and
double-letter aliases: `e` and `e2` for the referenced audit entity, `ee` and `ee2` for the audit entity that backs a
link table, `f` and `f2` for an index entity. These aliases are literals embedded in the query-generation classes.

Reading a historical snapshot of an owning entity works. Reading a historical collection that is stored through a
link table fails when the referenced audit entity's fully qualified name begins with a segment identical to an alias
that the enclosing statement already declares. The generated text reads as

```
select new list(ee, e) from <middle audit entity> ee, ee.estonia.entities.Child_AUD e
where ... and e.revision = (select max(e2.revision) from ee.estonia.entities.Child_AUD e2 where ...)
```

The outer source list tolerates the qualified name. In
`hibernate-core/src/main/java/org/hibernate/hql/internal/ast/tree/FromElementFactory.java`, `addFromElement` consults
enclosing aliases only when a parent source list exists:

```java
FromElement addFromElement() throws SemanticException {
    FromClause parentFromClause = fromClause.getParentFromClause();
    if ( parentFromClause != null ) {
        String pathAlias = PathHelper.getAlias( path );
        FromElement parentFromElement = parentFromClause.getFromElement( pathAlias );
        if ( parentFromElement != null ) {
            return createFromElementInSubselect( path, pathAlias, parentFromElement, classAlias );
        }
    }
    EntityPersister entityPersister = fromClause.getSessionFactoryHelper().requireClassPersister( path );
    ...
```

`PathHelper.getAlias` is `StringHelper.root(path)`, the text before the first dot, so for
`ee.estonia.entities.Child_AUD` the token offered to the enclosing lookup is `ee`.

At the outermost level the parent is absent, so the whole dotted path is taken as an entity name. The failure comes
from the correlated subquery that the audit strategy nests into the same statement: there a parent source list does
exist, the leading segment of the qualified name is looked up as an enclosing alias, the alias declared by the
generator is found, and the remainder of the path is resolved as a property, which fails while naming the second
package segment as an unresolvable property of the type that backs the link table. Moving the classes into a package
whose leading segment matches no declared alias removes the ambiguity and the same mapping works.

## Where the statement text is composed

`hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/TwoEntityQueryGenerator.java`
composes the whole statement inside its **constructor**, and stores the finished text in the final field
`queryString`:

```java
QueryBuilder qb = new QueryBuilder(versionsMiddleEntityName, "ee");
qb.addFrom(referencedIdData.getAuditEntityName(), "e");
qb.addProjection("new list", "ee, e", false, false);
...
auditStrategy.addEntityAtRevisionRestriction(globalCfg, qb, "e." + revisionPropertyPath,
        "e." + verEntCfg.getRevisionEndFieldName(), false,
        referencedIdData, revisionPropertyPath, originalIdPropertyName, "e", "e2");
auditStrategy.addAssociationAtRevisionRestriction(qb, revisionPropertyPath,
        verEntCfg.getRevisionEndFieldName(), true, referencingIdData, versionsMiddleEntityName,
        eeOriginalIdPropertyPath, revisionPropertyPath, originalIdPropertyName, componentDatas);
...
StringBuilder sb = new StringBuilder();
qb.build(sb, Collections.<String, Object>emptyMap());
queryString = sb.toString();
```

Two decisions taken in this constructor create the whole situation. It declares the literal alias `ee` for the
link-table audit entity by handing that alias to the `QueryBuilder` constructor, which is the token that later gets
matched. It then brings the referenced type's fully qualified audit entity name into the same statement, both through
`qb.addFrom(referencedIdData.getAuditEntityName(), "e")` and by passing `referencedIdData` together with the alias
pair `"e"` and `"e2"` into `auditStrategy.addEntityAtRevisionRestriction`, which is what places that qualified name
inside a nested source list. So this one constructor supplies both halves of the collision: the enclosing alias that
will be found, and the qualified name whose leading segment will be looked up.

`MiddleIdData.getAuditEntityName()` returns `verEntCfg.getAuditEntityName(entityName)`, which is
`auditTablePrefix + entityName + auditTableSuffix`, so the package of the referenced class is carried into the
statement untouched.

The constructor runs during mapping construction, long before any read. The routine that the failing call actually
enters is

```java
public Query getQuery(AuditReaderImplementor versionsReader, Object primaryKey, Number revision) {
    Query query = versionsReader.getSession().createQuery(queryString);
    ...
}
```

which only replays the stored text and binds parameters. This split is the heart of the localization: the failure is
observed inside `getQuery` at collection-read time, yet the defective text was fixed at construction time and
`getQuery` composes nothing.

## How this generator is selected among its siblings

`hibernate-envers/src/main/java/org/hibernate/envers/configuration/metadata/QueryGeneratorBuilder.java` owns the
choice in `build(MiddleComponentData...)`:

```java
if (idDatas.size() == 0) {
    return new OneEntityQueryGenerator(...);
} else if (idDatas.size() == 1) {
    if (idDatas.get(0).isAudited()) {
        return new TwoEntityQueryGenerator(...);
    } else {
        return new TwoEntityOneAuditedQueryGenerator(...);
    }
} else if (idDatas.size() == 2) {
    ...
    return new ThreeEntityQueryGenerator(...);
}
```

The relations are accumulated by `addRelation(MiddleIdData)` while `CollectionMetadataGenerator` walks the mapping. A
set-valued association through a link table whose target type is itself tracked yields one related id data whose
`isAudited()` is true, which is precisely the branch that instantiates `TwoEntityQueryGenerator`. A target type left
out of tracking takes the sibling branch and lands on `TwoEntityOneAuditedQueryGenerator`, and an indexed or
map-keyed collection adds a second related id data and takes the three-entity branch.

## The routines that contribute further fragments

`hibernate-envers/src/main/java/org/hibernate/envers/tools/query/QueryBuilder.java` accumulates the sources as pairs
in its `froms` list. `getFromList()` renders each pair as `entityName + " " + alias`, and `build(StringBuilder, Map)`
joins them with commas after the `from` keyword. `QueryBuilder` chooses no alias of its own for these sources; it
records whatever its callers supply, which is why it is a carrier and not the origin, and why the alias choice stays
with the generator constructor.

`hibernate-envers/src/main/java/org/hibernate/envers/strategy/DefaultAuditStrategy.java` adds the correlated
subqueries, and it is inside one of them that the parse actually breaks. `addEntityAtRevisionRestriction` receives the
alias pair `e` and `e2` and the `MiddleIdData` for the referenced type as arguments from the generator, and builds
`newSubQueryBuilder(idData.getAuditEntityName(), alias2)`, which places the referenced type's qualified audit entity
name into a nested source list where the enclosing aliases are visible. `addAssociationAtRevisionRestriction` embeds
its own literal `"ee2"` through `newSubQueryBuilder(versionsMiddleEntityName, "ee2")`, but its source is the
link-table audit entity, whose name is derived from a table name and carries no package, so that literal collides
with nothing.

The strategy is a collaborator rather than the origin. It chooses neither the enclosing alias nor the qualified name:
both arrive as arguments from the generator constructor. Its subquery is what makes the enclosing alias consultable,
while the generator is what put a colliding alias there to be found.

## The runtime path that surfaces the failure

`hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/lazy/initializor/AbstractCollectionInitializor.java`
holds

```java
public T initialize() {
    List<?> collectionContent = queryGenerator.getQuery(versionsReader, primaryKey, revision).list();
    ...
}
```

so the failing call is `getQuery(...)` followed immediately by `list()` on the query it returns.

`queryGenerator` is typed as the one-method interface `RelationQueryGenerator`, declared in
`hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/RelationQueryGenerator.java`
with `getQuery` as its single member, so the runtime path exposes only `getQuery` and hides which of the five
implementations is behind it. An investigation that follows the failure backwards therefore arrives at an interface
and has to consult the selection logic to learn which concrete constructor produced the text.

## Why the owning record's own snapshot reads cleanly

`AuditReaderImpl.find(Class, String, Object, Number)` routes a single-record historical read through
`createQuery().forEntitiesAtRevision(...)`, which is
`hibernate-envers/src/main/java/org/hibernate/envers/query/impl/EntitiesAtRevisionQuery.java`. That class inherits
its root builder from `AbstractAuditQuery`, whose constructor does

```java
qb = new QueryBuilder(versionsEntityName, "e");
```

and its `list()` then calls the very same `addEntityAtRevisionRestriction(..., "e", "e2")`, nesting the owning type's
own fully qualified audit entity name in a correlated subquery. The enclosing statement here declares one source
under the single alias `e`. The leading segment of the qualified name is `ee`, the lookup of `ee` among the enclosing
aliases finds nothing, and the path is taken as an entity name. That is why the scalar read of the owning record
succeeds under exactly the package that breaks the collection read.

## What the merged change did

A new class `QueryConstants` was introduced in the same query package holding
`REFERENCED_ENTITY_ALIAS = "e__"`, `REFERENCED_ENTITY_ALIAS_DEF_AUD_STR = "e2__"`, `INDEX_ENTITY_ALIAS = "f__"`,
`INDEX_ENTITY_ALIAS_DEF_AUD_STR = "f2__"`, `MIDDLE_ENTITY_ALIAS = "ee__"`,
`MIDDLE_ENTITY_ALIAS_DEF_AUD_STR = "ee2__"`, plus `REVISION_PARAMETER` and `DEL_REVISION_TYPE_PARAMETER`. Every
literal alias in the five generators, in both audit strategies and in the entity-level query classes was replaced by
these constants. The trailing underscores make the aliases unusable as a leading package segment, so the ambiguity
disappears while the statement structure stays identical. Behaviour changes only for models whose package names
previously collided.

## The true routine versus the routines that look equally guilty

**`TwoEntityQueryGenerator.getQuery` is the most tempting wrong pick.** It is the frame the failure is raised from, it
is the only member of the interface, and it is where `createQuery` is called. It composes nothing: it reads the
`queryString` field that the constructor filled in, so changing it would repair nothing.

**`QueryBuilder.build` and `QueryBuilder.getFromList` are the second temptation.** They perform the concatenation that
produces the ambiguous text and they are shared by every generator, which makes them look like the common origin. They
receive both aliases and entity names as parameters and invent neither, so the collision is decided before control
reaches them.

**`FromElementFactory.addFromElement` in hibernate-core is the third temptation.** It is where the enclosing-alias
lookup happens and where the resolution error is raised, but its rule is the ordinary behaviour of subquery
correlation and is shared by every HQL statement in the product. Blaming it mistakes the general rule for the
particular caller that walked into it.

**`OneAuditEntityQueryGenerator` is the sibling that looks equally suspect and is safe.** Its constructor also embeds
literal aliases, `new QueryBuilder(versionsReferencedEntityName, "e")` and the pair `"e"`/`"e2"`, it serves collections
of tracked entities, and it drives the very same strategy call, so it nests a subquery over the same qualified name.
It is also the one generator that `QueryGeneratorBuilder` never returns: `CollectionMetadataGenerator` instantiates it
directly for a collection that needs no link table, which is why it is easy to reach it first when tracing backwards
from a collection read and to stop there.
It stays safe for the reported package because the only alias its enclosing statement declares is `e`, while the
leading segment of the qualified name is `ee`. The lookup of the enclosing alias therefore finds nothing and the
qualified path is taken as an entity name. This is the sharpest available demonstration that neither literal aliases
nor nested subqueries are harmful in themselves: harm needs an enclosing alias that is character-for-character the
leading segment of a qualified name used inside a nested source list.

**`ThreeEntityQueryGenerator` carries the same defect** but is reached only for an indexed or map-keyed collection, so
it is never selected for the reported mapping.

**`TwoEntityOneAuditedQueryGenerator` is a second safe sibling.** It declares the same literal `ee` and puts the
referenced type's name in its outer source list, yet it drives only `addAssociationAtRevisionRestriction`, whose nested
source is the link-table audit entity name. That name is derived from a table name and carries no package, so no
qualified name ever reaches a nested source list from this generator. This is exactly why the reported collection whose
target type is left out of tracking keeps working, and it is the reason the sibling worth discussing is
`OneAuditEntityQueryGenerator`, the one the report never mentions.

**`DefaultAuditStrategy.addEntityAtRevisionRestriction` is the deepest temptation of all,** because the frame that
raises the failure sits under it and it does place the qualified name into the nested source list. It is still a
collaborator: the alias it nests under and the entity name it nests are both handed to it by the generator, and it is
shared by every generator including the safe sibling, so it explains none of the difference between them.

## Why several files must be read

The failing frame lives in the collection initializor, the interface it calls through hides the implementation, the
selection among five near-identical implementations lives in the configuration package, the text assembly lives in the
query-builder utility, and part of the text arrives from the audit strategy. Only after reading the selection logic and
the builder's rendering of the source list can the composing constructor be picked out and the safe sibling be
explained.

```json <!-- gold -->
{
  "file": "hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/TwoEntityQueryGenerator.java",
  "function": "TwoEntityQueryGenerator(GlobalConfiguration, AuditEntitiesConfiguration, AuditStrategy, String, MiddleIdData, MiddleIdData, MiddleComponentData...) constructor",
  "explanation": "The constructor of TwoEntityQueryGenerator composes the entire statement once, at mapping-construction time, and stores it in the final queryString field, whereas the call that fails happens much later, when the historical collection on a returned snapshot is read; the two are separate lifecycle stages. It declares the link-table audit entity under the literal alias ee by passing that alias to the QueryBuilder constructor, and it brings the referenced type's fully qualified audit entity name into the same statement twice, through qb.addFrom(referencedIdData.getAuditEntityName(), \"e\") and through auditStrategy.addEntityAtRevisionRestriction, to which it hands referencedIdData together with the alias pair e and e2. DefaultAuditStrategy.addEntityAtRevisionRestriction nests that qualified name in a correlated subquery via newSubQueryBuilder, and FromElementFactory.addFromElement consults enclosing aliases only when a parent source list exists, so inside that subquery the leading package segment of the qualified name is looked up as an enclosing alias, the constructor's ee is found, and the remainder of the path is then resolved as a property of the link-table audit entity, which fails. QueryGeneratorBuilder.build is what picks this class out of its siblings: it selects TwoEntityQueryGenerator for a set-valued association through a link table whose target type is itself tracked, namely one accumulated related id data whose isAudited() is true, and it routes the same mapping to TwoEntityOneAuditedQueryGenerator when the target type is left out of tracking. QueryBuilder is only the carrier: it accumulates its sources as entity-name and alias pairs, getFromList renders each pair as the entity name followed by its alias, build joins the rendered sources with commas after the from keyword, and it records whatever alias its callers hand it, so the choice of alias rests with the generator constructor; DefaultAuditStrategy likewise receives the alias pair and the referenced id data as arguments from that constructor. The failing call arrives through AbstractCollectionInitializor.initialize, which calls list() on the query returned by getQuery, and queryGenerator there is typed as the one-method interface RelationQueryGenerator that exposes getQuery alone and hides which concrete implementation produced the text. TwoEntityQueryGenerator.getQuery is the frame the failure surfaces in, yet it only calls createQuery on the stored text and composes nothing. OneAuditEntityQueryGenerator drives the same strategy call over the same qualified name and stays safe, because the only alias its enclosing statement declares is e, so the lookup of the leading segment ee finds nothing there; the owning record's own snapshot read succeeds for the same reason, since EntitiesAtRevisionQuery inherits from AbstractAuditQuery a root builder created as new QueryBuilder(versionsEntityName, \"e\"), leaving its nested subquery surrounded by the single alias e that differs from the leading package segment. Harm therefore needs an enclosing alias that is character-for-character the leading segment of a qualified name used inside a nested source list."
}
```
